#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
百度贴吧全自动签到
- 客户端接口 + MD5 签名（经验 +8，比 web 端多）
- 自动翻页拉取全部关注贴吧（突破单页 200 限制）
- 多轮重试、失败分类统计
- 可选推送：Server酱 / PushPlus / 企业微信机器人（不配则只输出日志）

环境变量：
    BDUSS        必填，贴吧登录凭证
    PUSH_TYPE    可选：serverchan | pushplus | wecom
    PUSH_KEY     可选：对应渠道的 key/token/webhook-key
"""
import hashlib
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

SIGN_KEY = "tiebaclient!!!"
BJ = timezone(timedelta(hours=8))

BASE_PARAMS = {
    "_client_type": "2",
    "_client_version": "9.7.8.0",
    "_phone_imei": "000000000000000",
    "model": "MI+5",
    "net_type": "1",
}

UA = (
    "Mozilla/5.0 (Linux; Android 12; MI 5 Build/SKQ1.211019.001; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/95.0.4638.69 Mobile Safari/537.36"
)

# 签到状态码归类
EXIST_CODES = ("160002",)  # 亲，你之前已经签过了
EXIST_KEYWORDS = ("已签到", "已经签到", "已签过", "签过了", "already")
SHIELD_CODES = ("340006", "340007", "340008", "340009")
SHIELD_KEYWORDS = ("屏蔽", "封禁", "禁言", "不存在", "黑名单")


def log(msg):
    print(f"[{datetime.now(BJ).strftime('%H:%M:%S')}] {msg}", flush=True)


def md5_sign(data):
    raw = "".join(f"{k}={data[k]}" for k in sorted(data))
    return hashlib.md5((raw + SIGN_KEY).encode()).hexdigest().upper()


class TiebaSigner:
    def __init__(self, bduss, stoken=None):
        self.bduss = bduss
        self.stoken = stoken
        self.s = requests.Session()
        self.s.trust_env = False  # 绕开本机可能残留的失效代理
        self.s.headers.update({
            "User-Agent": UA,
            "Referer": "https://tieba.baidu.com/",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        ck = {"BDUSS": bduss}
        if stoken:
            ck["STOKEN"] = stoken
        requests.utils.add_dict_to_cookiejar(self.s.cookies, ck)
        self.tbs = None
        self._tbs_count = 0

    # ---------- 基础 ----------
    def refresh_tbs(self):
        for attempt in range(3):
            try:
                r = self.s.get("https://tieba.baidu.com/dc/common/tbs", timeout=15)
                j = r.json()
                if j.get("is_login") == 1:
                    self.tbs = j["tbs"]
                    self._tbs_count += 1
                    return True
                log(f"!! 未登录（is_login={j.get('is_login')}），BDUSS 可能已失效")
                return False
            except Exception as e:
                log(f"!! 获取 tbs 失败({attempt + 1}/3): {e}")
                time.sleep(2)
        return False

    def _post(self, url, extra, retry=2):
        data = dict(BASE_PARAMS)
        data.update(extra)
        data["sign"] = md5_sign(data)
        for i in range(retry + 1):
            try:
                r = self.s.post(url, data=data, timeout=20)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if i == retry:
                    return {"error_code": "EXC", "error_msg": str(e)}
                time.sleep(1.5 * (i + 1))

    # ---------- 关注列表 ----------
    def fetch_forums(self):
        forums, page = {}, 1
        while page <= 20:
            j = self._post("https://c.tieba.baidu.com/c/f/forum/like",
                           {"tbs": self.tbs, "page_no": str(page), "page_size": "200"})
            if j.get("error_code") not in (0, "0", None):
                log(f"   列表第 {page} 页失败: {j.get('error_code')} {j.get('error_msg')}")
                break
            raw = j.get("forum_list") or []
            lst = (raw.get("non-gconforum", []) + raw.get("gconforum", [])) \
                if isinstance(raw, dict) else raw
            if not lst:
                break
            new = 0
            for f in lst:
                name = f.get("name")
                if name and name not in forums:
                    forums[name] = f
                    new += 1
            log(f"   列表第 {page} 页: {len(lst)} 条，新增 {new}，累计 {len(forums)}")
            if new == 0 or len(lst) < 200:
                break
            page += 1
            time.sleep(0.4)
        return list(forums.values())

    # ---------- 签到 ----------
    def sign_one(self, forum):
        payload = {"tbs": self.tbs, "kw": forum.get("name", "")}
        fid = forum.get("id")
        if fid:
            payload["fid"] = fid
        j = self._post("https://c.tieba.baidu.com/c/c/forum/sign", payload)
        code = str(j.get("error_code", "?"))
        msg = str(j.get("error_msg") or "")
        info = j.get("user_info") or {}

        if code == "0":
            bonus = info.get("sign_bonus_point", "?")
            rank = info.get("user_sign_rank", "")
            extra = f" +{bonus}经验" if bonus not in ("?", None) else ""
            extra += f" 第{rank}个" if rank else ""
            return "success", extra.strip()
        if code in EXIST_CODES or any(k in msg for k in EXIST_KEYWORDS):
            return "exist", msg or code
        if code in SHIELD_CODES or any(k in msg for k in SHIELD_KEYWORDS):
            return "shield", msg or code
        return "fail", f"{code} {msg}".strip()


def batch_sign(signer, forums, delay=(0.45, 0.95), rest_every=30, rest=(2.0, 4.0)):
    stats = {"success": 0, "exist": 0, "shield": 0, "fail": 0}
    failed, shielded = [], []
    total = len(forums)
    for idx, f in enumerate(forums, 1):
        name = f.get("name", "?")
        status, detail = signer.sign_one(f)
        stats[status] += 1
        if status == "fail":
            failed.append(f)
            log(f"   [{idx}/{total}] {name} 失败: {detail}")
        elif status == "shield":
            shielded.append(name)
        elif idx % 50 == 0 or idx == total:
            log(f"   进度 {idx}/{total} | 成功 {stats['success']} 已签 {stats['exist']} "
                f"屏蔽 {stats['shield']} 失败 {stats['fail']}")

        time.sleep(random.uniform(*delay))
        if rest_every and idx % rest_every == 0:
            time.sleep(random.uniform(*rest))
        # 长时间运行 tbs 会过期，定期刷新
        if idx % 200 == 0 and not signer.refresh_tbs():
            log("!! tbs 刷新失败，剩余贴吧可能无法签到")
    return stats, failed, shielded


def push(title, content):
    ptype = os.environ.get("PUSH_TYPE", "").strip().lower()
    key = os.environ.get("PUSH_KEY", "").strip()
    if not ptype or not key:
        return
    try:
        if ptype == "serverchan":
            url = f"https://sctapi.ftqq.com/{key}.send"
            requests.post(url, data={"title": title, "desp": content},
                          timeout=15, proxies={})
        elif ptype == "pushplus":
            requests.post("https://www.pushplus.plus/send",
                          json={"token": key, "title": title,
                                "content": content.replace("\n", "<br>")},
                          timeout=15, proxies={})
        elif ptype == "wecom":
            requests.post(f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}",
                          json={"msgtype": "markdown", "markdown": {"content": content}},
                          timeout=15, proxies={})
        else:
            log(f"!! 未知 PUSH_TYPE: {ptype}")
    except Exception as e:
        log(f"!! 推送失败（不影响签到）: {e}")


def main():
    bduss = os.environ.get("BDUSS", "").strip()
    if not bduss:
        log("!! 缺少环境变量 BDUSS")
        return 2
    limit = int(os.environ.get("MAX_FORUMS", "0") or 0)

    signer = TiebaSigner(bduss, os.environ.get("STOKEN", "").strip() or None)

    log("① 校验登录态")
    if not signer.refresh_tbs():
        push("贴吧签到失败", "## 贴吧签到失败\n\nBDUSS 无效或已过期，请重新获取。")
        return 3

    log("② 拉取关注贴吧列表")
    forums = signer.fetch_forums()
    if not forums:
        log("!! 没拿到任何关注贴吧")
        return 4
    if limit:
        forums = forums[:limit]
    total_forums = len(forums)
    log(f"   共 {total_forums} 个贴吧待签到")
    t0 = time.time()

    # 预检查：多个定时点兜底时，已签过就早退，避免重复跑 27 分钟
    log("③ 预检查今日签到状态")
    probe_stats = {"success": 0, "exist": 0, "shield": 0, "fail": 0}
    probed_names = []
    signed_today = None
    for f in forums[:3]:
        st, _ = signer.sign_one(f)
        probe_stats[st] += 1
        probed_names.append(f.get("name"))
        if st == "success":
            signed_today = False  # 刚签成功 → 今天还没签
            break
        if st == "exist":
            signed_today = True  # 已签 → 今天已经跑过了
            break

    if signed_today:
        log("   探测贴吧返回「已签到」，今天已签过，本次直接结束")
        log(f"   耗时 {int(time.time() - t0)}s")
        return 0

    log("   今天尚未签到，继续全量")
    # 探测时已处理的贴吧从列表中移除，其统计稍后合并
    forums = [f for f in forums if f.get("name") not in probed_names]
    log(f"   剩余 {len(forums)} 个待签")

    log("④ 开始签到")
    stats, failed, shielded = batch_sign(signer, forums)
    for k in probe_stats:
        stats[k] += probe_stats[k]

    # 失败重试一轮（重试前先扣掉这轮的 fail 计数，避免重复累加）
    if failed:
        log(f"⑤ 重试 {len(failed)} 个失败贴吧")
        signer.refresh_tbs()
        n_failed = len(failed)
        s2, failed2, _ = batch_sign(signer, failed, delay=(1.5, 2.5), rest_every=0)
        stats["fail"] -= n_failed
        for k in ("success", "exist", "shield", "fail"):
            stats[k] += s2[k]
        failed = failed2

    elapsed = int(time.time() - t0)
    total = total_forums
    ok = stats["success"] + stats["exist"]
    rate = ok / total * 100 if total else 0

    log("=" * 52)
    log(f"完成 | 共 {total} 个 | 成功 {stats['success']} | 已签 {stats['exist']} "
        f"| 屏蔽 {stats['shield']} | 失败 {stats['fail']}")
    log(f"成功率 {rate:.1f}% | 耗时 {elapsed // 60}分{elapsed % 60}秒")
    if failed:
        log(f"失败贴吧: {', '.join(f.get('name', '?') for f in failed[:40])}")
    log("=" * 52)

    lines = [
        f"### 贴吧签到 {datetime.now(BJ).strftime('%Y-%m-%d %H:%M')}",
        f"> 共 **{total}** 个 | 成功 **{stats['success']}** | 已签 {stats['exist']} "
        f"| 屏蔽 {stats['shield']} | 失败 {stats['fail']}",
        f"> 成功率 {rate:.1f}%，耗时 {elapsed // 60}分{elapsed % 60}秒",
    ]
    if failed:
        lines.append("> 失败：" + "、".join(f.get("name", "?") for f in failed[:30]))
    push(f"贴吧签到 {ok}/{total}", "\n".join(lines))

    return 0 if stats["fail"] == 0 or rate >= 90 else 1


if __name__ == "__main__":
    sys.exit(main())
