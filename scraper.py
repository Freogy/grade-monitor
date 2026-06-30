"""
浙大教务系统爬虫模块 (zdbk zju.edu.cn)
通过 CAS 统一认证登录 → 进入教务系统 → 抓取成绩。

登录流程:
1. GET 教务首页 → 302 重定向到 CAS login
2. GET CAS 登录页 → 提取 execution token
3. GET v2/getPubKey → 获取 RSA 公钥
4. 密码反转后 RSA 加密
5. GET v2/getKaptchaStatus → 检查是否需要验证码
6. POST CAS login → 302 重定向回教务系统
7. 在教务系统中查找成绩页面 → 解析
"""

import re
import json
import logging
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup
import urllib3

from config import PORTAL_URL, STUDENT_ID, PASSWORD

# 禁用 SSL 警告（校内系统可能使用自签名证书）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# --- 常量 ---
JWGLXT_URL = PORTAL_URL + "/jwglxt"  # 教务管理系统
CAS_BASE = "https://zjuam.zju.edu.cn/cas"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class LoginError(Exception):
    """登录异常"""
    pass


class ScrapeError(Exception):
    """抓取异常"""
    pass


def _rsa_encrypt_password(password: str, modulus_hex: str, exponent_hex: str) -> str:
    """
    模拟浙大 CAS 的 RSA 加密：
    1. 反转密码字符串
    2. 用公钥 (n, e) 逐块加密
    3. 返回 hex 字符串（空格分隔），每个块补齐到与 modulus 等长
    """
    # 反转密码
    reversed_pwd = password[::-1]

    # 解析公钥
    n = int(modulus_hex, 16)
    e = int(exponent_hex, 16)

    # 期望的 hex 长度（与 modulus 对齐，4 的倍数）
    expected_hex_len = len(modulus_hex)
    # 向上取到 4 的倍数（匹配 JS digitToHex 的 4 字符/digit 格式）
    if expected_hex_len % 4 != 0:
        expected_hex_len = ((expected_hex_len // 4) + 1) * 4

    # chunkSize: 密钥的字节数 = (modulus 位数 - 1) * 2 字节
    # biHighIndex 返回最高非零位索引，chunkSize = 2 * biHighIndex
    chunk_size = _get_chunk_size(n)

    result_blocks = []

    # 字符串 -> 字节数组
    data = [ord(c) for c in reversed_pwd]

    # 填充到 chunk_size 的整数倍
    while len(data) % chunk_size != 0:
        data.append(0)

    # 逐块加密
    for i in range(0, len(data), chunk_size):
        block = 0
        for j in range(chunk_size - 1, -1, -1):
            block = (block << 8) | data[i + j]

        # RSA 加密: block^e mod n
        encrypted = pow(block, e, n)
        hex_str = f"{encrypted:x}"
        # 补齐到期望长度（匹配 JS biToHex 的 digitToHex 4字符对齐）
        if len(hex_str) < expected_hex_len:
            hex_str = hex_str.zfill(expected_hex_len)
        result_blocks.append(hex_str)

    return " ".join(result_blocks)


def _get_chunk_size(n: int) -> int:
    """
    计算 RSA 密钥的 chunk size。
    chunkSize = 2 * biHighIndex(m)
    biHighIndex = 最高非零 digit 的索引
    每个 digit 是 16 bits
    """
    # n 以 16-bit digits 计算需要多少个
    if n == 0:
        return 2
    # 计算最高非零 digit 索引
    bits = n.bit_length()
    digits = (bits + 15) // 16  # 每个 digit 16 bits
    return 2 * (digits - 1)  # biHighIndex = digits - 1


class JwxtScraper:
    """浙大教务系统爬虫"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.verify = False  # 校内系统可能有自签名证书
        self.logged_in = False
        self.jwglxt_base = JWGLXT_URL

    def _get(self, url: str, referer: str = None, allow_redirects: bool = True) -> requests.Response:
        """GET 请求"""
        headers = {}
        if referer:
            headers["Referer"] = referer
        resp = self.session.get(url, headers=headers, timeout=30,
                                 allow_redirects=allow_redirects)
        resp.raise_for_status()
        return resp

    def _post(self, url: str, data: dict, referer: str = None,
              allow_redirects: bool = True) -> requests.Response:
        """POST 请求"""
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if referer:
            headers["Referer"] = referer
        resp = self.session.post(url, data=data, headers=headers, timeout=30,
                                  allow_redirects=allow_redirects)
        resp.raise_for_status()
        return resp

    def login(self) -> bool:
        """
        CAS 统一认证登录流程。
        """
        logger.info("=" * 50)
        logger.info("[CAS] 开始 CAS 统一认证登录...")

        # === Step 1: 访问教务系统，触发 CAS 重定向 ===
        logger.info("[Step1] 访问教务系统入口...")
        try:
            # 先允许跟随重定向，让系统自动跳转到 CAS
            resp = self._get(
                f"{self.jwglxt_base}/xtgl/login_slogin.html?language=zh_CN",
                allow_redirects=True  # 跟随 HTTP 重定向
            )
        except requests.RequestException as e:
            raise LoginError(f"无法访问教务系统: {e}")

        # 检查最终 URL（可能已被重定向到 CAS）
        final_url = resp.url
        logger.info(f"  -> 最终 URL: {final_url[:100]}...")

        # 如果不在 CAS 页面，检查是否有 JS 重定向
        if "zjuam.zju.edu.cn" not in final_url:
            logger.info("  -> 未自动跳转到 CAS，检查页面中是否有重定向...")
            soup = BeautifulSoup(resp.text, "lxml")
            # 查找可能的 JS 重定向或 meta refresh
            redirect_found = False
            for script in soup.find_all("script"):
                text = script.get_text()
                # 查找 window.location.href 或 window.location.replace
                match = re.search(r"location\.(?:href|replace)\s*=\s*['\"]([^'\"]+)['\"]", text)
                if match:
                    js_redirect = match.group(1)
                    if js_redirect.startswith("/"):
                        js_redirect = f"https://zjuam.zju.edu.cn{js_redirect}"
                    logger.info(f"  -> 发现 JS 重定向: {js_redirect[:100]}...")
                    try:
                        resp = self._get(js_redirect, allow_redirects=True)
                        final_url = resp.url
                        redirect_found = True
                    except requests.RequestException:
                        pass
                    break

            if not redirect_found:
                # 尝试直接构造 CAS 登录 URL
                cas_login_url = (
                    f"https://zjuam.zju.edu.cn/cas/login"
                    f"?service=https%3A%2F%2Fzdbk.zju.edu.cn"
                    f"%2Fjwglxt%2Fxtgl%2Flogin_ssologin.html"
                )
                logger.info(f"  -> 手动构造 CAS URL: {cas_login_url[:100]}...")
                try:
                    resp = self._get(cas_login_url, allow_redirects=False)
                    final_url = cas_login_url
                except requests.RequestException as e:
                    raise LoginError(f"无法访问 CAS: {e}")

        # 确保我们在 CAS 登录页面
        if "zjuam.zju.edu.cn" not in final_url:
            raise LoginError(f"未能进入 CAS 登录页面，当前 URL: {final_url}")

        cas_login_url = final_url
        logger.info(f"  -> CAS 登录页: {cas_login_url[:100]}...")

        # === Step 2: 获取 CAS 登录页，提取 execution token ===
        logger.info("Step 2: 获取 CAS 登录页...")
        try:
            cas_page = self._get(cas_login_url)
        except requests.RequestException as e:
            raise LoginError(f"无法访问 CAS 登录页: {e}")

        cas_soup = BeautifulSoup(cas_page.text, "lxml")

        # 提取 execution
        execution_input = cas_soup.find("input", {"name": "execution"})
        if not execution_input:
            raise LoginError("CAS 登录页未找到 execution 字段")
        execution = execution_input.get("value", "")
        logger.info(f"  -> execution: {execution[:40]}...")

        # === Step 3: 获取 RSA 公钥 ===
        logger.info("Step 3: 获取 RSA 公钥...")
        try:
            pubkey_resp = self._get(
                f"{CAS_BASE}/v2/getPubKey",
                referer=cas_login_url
            )
            pubkey_data = pubkey_resp.json()
            modulus = pubkey_data["modulus"]
            exponent = pubkey_data["exponent"]
            logger.info(f"  -> 公钥已获取 (modulus 长度: {len(modulus)})")
        except Exception as e:
            raise LoginError(f"获取 RSA 公钥失败: {e}")

        # === Step 4: 检查是否需要验证码 ===
        logger.info("Step 4: 检查验证码状态...")
        try:
            kaptcha_resp = self._get(
                f"{CAS_BASE}/v2/getKaptchaStatus",
                referer=cas_login_url
            )
            need_kaptcha = kaptcha_resp.text.strip().lower() == "true"
        except Exception:
            need_kaptcha = False

        captcha_code = ""
        if need_kaptcha:
            logger.warning("[WARN] 需要验证码！")
            # 下载验证码图片
            try:
                img_resp = self._get(
                    f"{CAS_BASE}/kaptcha",
                    referer=cas_login_url
                )
                # 保存验证码图片供人工识别
                with open("captcha.png", "wb") as f:
                    f.write(img_resp.content)
                logger.info("验证码已保存为 captcha.png，请查看并输入: ")
                captcha_code = input("请输入验证码: ").strip()
            except Exception as e:
                raise LoginError(f"验证码获取失败: {e}")
        else:
            logger.info("  -> 无需验证码 [v]")

        # === Step 5: RSA 加密密码 ===
        logger.info("Step 5: 加密密码...")
        encrypted_pwd = _rsa_encrypt_password(PASSWORD, modulus, exponent)
        logger.info(f"  -> 密码已加密 (密文长度: {len(encrypted_pwd)})")

        # === Step 6: POST 登录 ===
        logger.info("Step 6: 提交登录表单...")
        login_data = {
            "username": STUDENT_ID,
            "password": encrypted_pwd,
            "execution": execution,
            "_eventId": "submit",
            "rememberMe": "true",
        }
        if need_kaptcha and captcha_code:
            login_data["authcode"] = captcha_code

        try:
            login_resp = self._post(
                cas_login_url,
                data=login_data,
                referer=cas_login_url,
                allow_redirects=False
            )
        except requests.RequestException as e:
            raise LoginError(f"登录请求失败: {e}")

        # === Step 7: 处理登录结果 ===
        logger.info(f"  -> 登录响应状态码: {login_resp.status_code}")

        if login_resp.status_code in (302, 301):
            location = login_resp.headers.get("Location", "")
            logger.info(f"  -> 重定向: {location[:100]}...")

            if "ticket" in location.lower():
                # CAS 签发 ticket，跟随重定向
                logger.info("  -> CAS 签发 ticket，跟随重定向...")
                try:
                    self._get(location, allow_redirects=True)
                except requests.RequestException:
                    pass
                self.logged_in = True
                logger.info("[OK] CAS 登录成功！")
            elif "service" in location.lower():
                # 回到教务系统
                try:
                    self._get(location, allow_redirects=True)
                except requests.RequestException:
                    pass
                self.logged_in = True
                logger.info("[OK] CAS 登录成功！")
            else:
                # 可能在 CAS 页面，手动跟进
                try:
                    self._get(location, allow_redirects=True)
                except requests.RequestException:
                    pass
                self.logged_in = True
                logger.info("[OK] 登录流程完成")
        else:
            # 检查是否有错误消息
            soup = BeautifulSoup(login_resp.text, "lxml")
            error_msg = soup.find("p", {"id": "errormsg"})
            error_text = error_msg.get_text(strip=True) if error_msg else ""
            if error_text:
                raise LoginError(f"登录失败: {error_text}")
            elif "用户名" in login_resp.text and "password" in login_resp.text:
                raise LoginError("登录失败: 账号或密码错误")
            elif "验证码" in login_resp.text:
                raise LoginError("登录失败: 验证码错误")
            else:
                # 可能 JS 提交后直接成功了
                self.logged_in = True
                logger.info("[OK] 登录成功")

        if not self.logged_in:
            raise LoginError("登录失败: 未收到有效重定向")

        # === Step 8: 验证教务系统 session ===
        logger.info("Step 8: 验证教务系统 session...")
        try:
            main_page = self._get(
                f"{self.jwglxt_base}/xtgl/index_initMenu.html",
                allow_redirects=False
            )
            if main_page.status_code == 200:
                self.logged_in = True
                logger.info("[OK] 教务系统 session 有效")
            else:
                logger.warning(f"教务系统入口返回 {main_page.status_code}，可能未完全登录")
        except requests.RequestException as e:
            logger.warning(f"验证 session 失败: {e}")

        return self.logged_in

    def _discover_grade_urls(self) -> list[str]:
        """
        从教务系统菜单页面自动发现成绩查询页面 URL。
        """
        urls = []

        # 尝试获取菜单页面
        menu_urls = [
            f"{self.jwglxt_base}/xtgl/index_initMenu.html",
            f"{self.jwglxt_base}/xtgl/index_main.html",
            f"{self.jwglxt_base}/xtgl/index.html",
        ]

        for menu_url in menu_urls:
            try:
                resp = self._get(menu_url)
                soup = BeautifulSoup(resp.text, "lxml")

                # 查找所有链接，找包含"成绩"关键词的
                for a in soup.find_all("a"):
                    href = a.get("href", "")
                    text = a.get_text(strip=True)
                    if "成绩" in text and href and href != "#":
                        full_url = urljoin(self.jwglxt_base, href)
                        urls.append(full_url)
                        logger.info(f"  -> 发现成绩相关链接: {text} -> {full_url}")

                # 也查 JavaScript 中的 URL
                for script in soup.find_all("script"):
                    text = script.get_text()
                    for pattern in [r"['\"](/[^'\"]*cj[^'\"]*)['\"]",
                                     r"['\"](/[^'\"]*grade[^'\"]*)['\"]",
                                     r"['\"](/[^'\"]*score[^'\"]*)['\"]"]:
                        for match in re.finditer(pattern, text, re.IGNORECASE):
                            path = match.group(1)
                            full_url = urljoin(self.jwglxt_base, path)
                            if full_url not in urls:
                                urls.append(full_url)

                if urls:
                    break
            except requests.RequestException:
                continue

        # 如果菜单中没找到，尝试常见的现代教务系统路径
        if not urls:
            urls = [
                f"{self.jwglxt_base}/cjcx/cjcx_cxDgXscj.html?gnmkdm=N305005",
                f"{self.jwglxt_base}/cjcx/cjcx_cxDgXscj.html?gnmkdm=N305005&layout=default",
                f"{self.jwglxt_base}/cjcx/cjcx_cxDgXscj.html",
                f"{self.jwglxt_base}/cjcx/xscj_cxXscjIndex.html?gnmkdm=N305005",
            ]

        return urls

    def fetch_grades(self) -> list[dict]:
        """
        抓取成绩列表。
        """
        if not self.logged_in:
            self.login()

        logger.info("=" * 50)
        logger.info("[DATA] 正在抓取成绩数据...")

        grades = []

        # 已知的浙大教务系统成绩页面
        grade_page_url = (
            f"{self.jwglxt_base}/cxdy/xscjcx_cxXscjIndex.html"
            f"?gnmkdm=N5083&layout=default&su={STUDENT_ID}"
        )
        logger.info(f"成绩页面: {grade_page_url}")

        try:
            # Step 1: GET 成绩页面
            resp = self._get(grade_page_url)
            if resp.status_code == 200:
                logger.info(f"页面加载成功 ({len(resp.text)} 字节)")

                # 尝试解析 HTML 表格
                grades = self._parse_grade_data(resp.text)

                # 如果 HTML 中没找到，尝试找内嵌的 JSON/Javascript 数据
                if not grades:
                    grades = self._parse_embedded_json(resp.text)

        except requests.RequestException as e:
            logger.error(f"访问成绩页面失败: {e}")
            return []

        # 如果 GET 直接有数据最好，否则尝试 POST 查询
        if not grades:
            logger.info("GET 未直接返回成绩，尝试 POST 查询...")
            grades = self._try_post_grade_query(grade_page_url, resp.text)

        logger.info(f"[DATA] 共抓取到 {len(grades)} 条成绩记录")
        return grades

    def _parse_embedded_json(self, html: str) -> list[dict]:
        """解析 HTML 中内嵌的 JSON 成绩数据"""
        grades = []
        soup = BeautifulSoup(html, "lxml")

        for script in soup.find_all("script"):
            text = script.get_text()
            # 查找 JSON 对象（包含成绩相关字段）
            for match in re.finditer(r'\{[^}]*"(?:kcmc|cj|xf|kcm|xnm|xqm|bfzcj)"[^}]*\}', text):
                try:
                    obj = json.loads(match.group())
                    if "kcmc" in obj or "kcm" in obj:
                        grades.append({
                            "course_name": obj.get("kcmc", obj.get("kcm", "")),
                            "grade": str(obj.get("cj", obj.get("bfzcj", ""))),
                            "credit": str(obj.get("xf", "")),
                            "semester": str(obj.get("xnm", "")) + "-" + str(obj.get("xqm", "")),
                            "course_type": str(obj.get("kclx", "")),
                        })
                except json.JSONDecodeError:
                    pass

        return grades

    def _fetch_grades_page(self, query_url: str, params: dict, referer: str) -> dict:
        """获取成绩数据（一次性获取全部，通过设置大 pageSize 绕过服务器分页限制）"""
        data = {
            "_search": "false",
            "nd": "",
            "rows": "2000",
            "page": "1",
            "pageSize": "2000",
            "limit": "2000",
            "sidx": "xkkh",
            "sord": "asc",
            **params,
        }
        resp = self._post(query_url, data, referer=referer)
        if resp.status_code != 200:
            return {"items": [], "totalResult": 0}
        return resp.json()

    def _parse_grade_items(self, items: list) -> list[dict]:
        """将 API 返回的 items 转换为成绩记录"""
        grades = []
        for item in items:
            xkkh = item.get("xkkh", "")
            # 从选课课号中提取学年学期
            semester = ""
            match = re.match(r"\((\d{4}-\d{4})-(\d)\)", xkkh)
            if match:
                year = match.group(1)
                term = match.group(2)
                term_name = {"1": "秋冬", "2": "春夏", "3": "短学期"}.get(term, term)
                semester = f"{year} {term_name}"

            grades.append({
                "course_name": item.get("kcmc", ""),
                "grade": str(item.get("cj", "")),
                "credit": str(item.get("xf", "")),
                "semester": semester,
                "course_type": "",
            })
        return grades

    def _try_post_grade_query(self, page_url: str, html: str) -> list[dict]:
        """POST 方式查询成绩 — 按学期组合查询并去重"""
        query_url = f"{self.jwglxt_base}/cxdy/xscjcx_cxXscjIndex.html?doType=query"
        seen_xkkh = set()
        all_grades = []

        # 学期组合：全部 + 各学年各学期逐一查询（规避服务器分页bug）
        queries = [
            {"xn": "", "xq": ""},
            {"xn": "2025-2026", "xq": "1"},
            {"xn": "2025-2026", "xq": "2"},
            {"xn": "2024-2025", "xq": "1"},
            {"xn": "2024-2025", "xq": "2"},
            {"xn": "2026-2027", "xq": "1"},
            {"xn": "2026-2027", "xq": "2"},
        ]

        for params in queries:
            try:
                result = self._fetch_grades_page(query_url, params, page_url)
                items = result.get("items", [])
                for item in items:
                    xkkh = item.get("xkkh", "")
                    if xkkh not in seen_xkkh:
                        seen_xkkh.add(xkkh)
                        xkkh_match = re.match(r"\((\d{4}-\d{4})-(\d)\)", xkkh)
                        semester = ""
                        if xkkh_match:
                            year = xkkh_match.group(1)
                            term = xkkh_match.group(2)
                            term_name = {"1": "秋冬", "2": "春夏", "3": "短学期"}.get(term, term)
                            semester = f"{year} {term_name}"
                        all_grades.append({
                            "course_name": item.get("kcmc", ""),
                            "grade": str(item.get("cj", "")),
                            "credit": str(item.get("xf", "")),
                            "semester": semester,
                            "course_type": "",
                        })
                logger.info(f"查询 {params}: {len(items)} 条")
            except Exception as e:
                logger.warning(f"查询 {params} 失败: {e}")
                continue

        logger.info(f"共解析 {len(all_grades)} 条成绩（去重后）")
        return all_grades

    def _parse_grade_data(self, html: str) -> list[dict]:
        """
        解析 HTML 中的成绩表格。
        支持多种教务系统的表格格式。
        """
        grades = []
        soup = BeautifulSoup(html, "lxml")

        # 也尝试从 script 标签中的 JSON 数据提取
        for script in soup.find_all("script"):
            text = script.get_text()
            if "成绩" in text or "grade" in text.lower() or "cj" in text:
                # 可能包含内嵌的成绩数据
                pass

        # 查找表格
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            # 检查表头
            headers = []
            for th in rows[0].find_all(["th", "td"]):
                headers.append(th.get_text(strip=True))
            header_str = "".join(headers)

            if not any(kw in header_str for kw in ["课程", "成绩", "学分"]):
                continue

            # 解析数据行
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                cell_texts = [c.get_text(strip=True) for c in cells]

                info = self._parse_row(cell_texts, headers)
                if info and info.get("course_name") and info.get("grade"):
                    grades.append(info)

        return grades

    def _parse_row(self, cells: list[str], headers: list[str]) -> Optional[dict]:
        """从表格行提取成绩信息"""
        result = {"course_name": "", "grade": "", "credit": "",
                   "semester": "", "course_type": ""}

        for i, h in enumerate(headers):
            if i >= len(cells):
                break
            val = cells[i]
            h = h.lower()
            if "课程" in h or "名称" in h:
                result["course_name"] = val
            elif "成绩" in h or "分数" in h:
                result["grade"] = val
            elif "学分" in h:
                result["credit"] = val
            elif "学期" in h:
                result["semester"] = val
            elif "类别" in h or "性质" in h:
                result["course_type"] = val

        # 启发式
        if not result["course_name"] and len(cells) >= 2:
            result["course_name"] = cells[0]
            for c in cells[1:]:
                if re.match(r"^[\d.]+$|^[A-D][+-]?$|^[优良中差]$|^通过|^不通过", c):
                    result["grade"] = c
                    break

        return result if result["course_name"] and result["grade"] else None


# --- 便捷函数 ---
def fetch_grades() -> list[dict]:
    """便捷函数: 登录并抓取成绩"""
    scraper = JwxtScraper()
    return scraper.fetch_grades()
