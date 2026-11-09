#!/usr/bin/env python3
"""data.yml から求人LPの静的HTMLを生成し、検査に通ったときだけ docs/ に書き出す。

使い方: python3 generator/build.py [--data PATH] [--out DIR] [--today YYYY-MM-DD]
"""
import argparse
import datetime as dt
import html
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / "generator"
CONFIG_JS = 'const APPLY_ENDPOINT = "";\n'
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


class BuildError(Exception):
    pass


e = html.escape


def yen(n):
    return f"{n:,}円"


def jp_date(d):
    return f"{d.year}年{d.month}月{d.day}日"


def source_label(fact):
    """出所と確認日のラベル。元の事実シートに確認日がない項目は日付を出さない。"""
    if "date_basis" in fact or "date_word" not in fact:
        return fact.get("source", "")
    return f"{fact['source']}・{jp_date(fact['confirmed_date'])}{fact['date_word']}"


def is_stale(fact, today, max_age):
    return (today - fact["confirmed_date"]).days > max_age


def walk(node):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


# ---------- 公開前の検査 ----------

def check_data(data, today):
    """日付と試算の検算。古い必須数値や計算の合わない試算があれば止める。"""
    site = data["site"]
    max_age = site["max_fact_age_days"]
    if today > site["valid_through"]:
        raise BuildError(f"募集の有効期限 {site['valid_through']} を過ぎています")
    founded = data["business"]["founded"]
    if today >= founded.replace(year=founded.year + 1):
        raise BuildError("開業から1年を過ぎました。代表あいさつの「開業1年未満」を直してください")
    for section, node in data.items():
        if section == "achievements":  # 実績は止めずに隠す
            continue
        for fact in walk(node):
            if not isinstance(fact, dict):
                continue
            for key, value in fact.items():
                if str(key).endswith("confirmed_date") and (today - value).days > max_age:
                    raise BuildError(f"確認日が{max_age}日を過ぎています: {section}.{key} = {value}")
    price = data["pay"]["unit_price"]
    for s in data["pay"]["scenarios"]:
        expected = (s["per_day"] * s["days"], s["jobs"] * price["min"] / 10000, s["jobs"] * price["max"] / 10000)
        if expected != (s["jobs"], s["min_man"], s["max_man"]):
            raise BuildError(f"試算の計算が合いません: {s['label']}")


def check_terms(pages, terms):
    hits = [f"{path}: 「{word}」→「{alt}」に直してください"
            for path, text in pages.items() if path.endswith((".html", ".js"))
            for word, alt in terms["ng"].items() if word in text]
    if hits:
        raise BuildError("NG語が含まれています\n  " + "\n  ".join(hits))
    missing = [word for word in terms["required"] if word not in pages["index.html"]]
    if missing:
        raise BuildError(f"LPに必要な言葉がありません: {missing}")


def visible_text(page):
    """本文の文字だけを取り出す。章番号や月の目盛り（class=num）は数値検査の対象外。"""
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S)
    page = re.sub(r'<(\w+) class="num"[^>]*>.*?</\1>', " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def allowed_numbers(data):
    allowed = set()
    for value in walk(data):
        if isinstance(value, str):
            allowed.update(n.replace(",", "") for n in NUMBER.findall(value))
        elif isinstance(value, dt.date):
            allowed.update({str(value.year), str(value.month), str(value.day)})
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            allowed.add(f"{value:g}")
    return allowed


def check_numbers(pages, data):
    allowed = allowed_numbers(data)
    hits = [f"{path}: {n}"
            for path, text in pages.items() if path.endswith(".html")
            for n in NUMBER.findall(visible_text(text)) if n.replace(",", "") not in allowed]
    if hits:
        raise BuildError("data.yml にない数値があります\n  " + "\n  ".join(hits))


def check_pages(pages, data):
    site = data["site"]
    tag = '<meta name="robots" content="noindex">'
    for path, text in pages.items():
        if path.endswith(".html") and site["noindex"] and tag not in text:
            raise BuildError(f"{path} に noindex がありません")
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', pages["index.html"], re.S)
    posting = json.loads(match.group(1))
    if "baseSalary" in posting or posting["employmentType"] != "CONTRACTOR":
        raise BuildError("JobPosting の内容が決めごとと違います")


# ---------- 部品 ----------

def layout(data, path, title, description, body, jsonld=None, apply_cta=True):
    biz = data["business"]
    depth = path.count("/")
    prefix = "../" * depth
    robots = '<meta name="robots" content="noindex">\n' if data["site"]["noindex"] else ""
    ld = ""
    if jsonld:
        ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>\n'
    apply_button = f'<a class="btn btn-primary" href="{prefix}apply/">面談を申し込む</a>' if apply_cta else ""
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
{robots}<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="stylesheet" href="{prefix}style.css">
{ld}</head>
<body>
<header class="site-header"><a href="{prefix or './'}">{e(biz['name'])}</a></header>
{body}
<footer class="site-footer">
<p><a href="{prefix}privacy/">個人情報の取り扱い</a></p>
<p>&copy; {e(biz['name'])}</p>
</footer>
<nav class="cta-bar" aria-label="お問い合わせ">
<a class="btn btn-tel" href="tel:{e(biz['phone'])}">電話する</a>
{apply_button}
</nav>
</body>
</html>
"""


def section(number, eyebrow, heading, body):
    return f"""<section class="block">
<p class="eyebrow"><span class="num">{number}</span>{e(eyebrow)}</p>
<h2>{e(heading)}</h2>
{body}
</section>
"""


def ul(items, cls=""):
    attr = f' class="{cls}"' if cls else ""
    return f"<ul{attr}>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>"


def rows(pairs):
    cells = "".join(f'<tr><th scope="row">{e(k)}</th><td>{v}</td></tr>' for k, v in pairs)
    return f'<table class="facts"><tbody>{cells}</tbody></table>'


def apply_block(prefix=""):
    return f'<p class="inline-cta"><a class="btn btn-primary" href="{prefix}apply/">面談を申し込む</a></p>'


def job_posting(data):
    site, biz, job = data["site"], data["business"], data["job"]
    return {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": job["title"],
        "description": f"<p>{job['description']}。業務委託契約です。</p>",
        "datePosted": str(site["date_posted"]),
        "validThrough": str(site["valid_through"]),
        "employmentType": "CONTRACTOR",
        "url": site["base_url"],
        "hiringOrganization": {"@type": "Organization", "name": biz["name"], "sameAs": biz["website"]},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressRegion": "愛媛県",
                "addressLocality": "松山市",
                "addressCountry": "JP",
            },
        },
    }


# ---------- ページ ----------

def render_index(data, today):
    site, biz, job, pay, area, contract = (data[k] for k in ("site", "business", "job", "pay", "area", "contract"))
    max_age = site["max_fact_age_days"]
    achievements = [a for a in data["achievements"] if not is_stale(a, today, max_age)]
    price = pay["unit_price"]
    price_range = f"{yen(price['min'])}〜{yen(price['max'])}"
    own = pay["own_estimate"]
    own_range = f"{own['min']}〜{own['max']}"

    hero = f"""<section class="hero">
<p class="hero-kicker">{e(site['area'])}エリア｜業務委託の職人を募集</p>
<h1>エアコンクリーニングの職人を、{e(site['area'])}で募集しています</h1>
<div class="hero-price">
<p class="hero-price-label">1件あたりの委託単価（{e(price['source'])}）</p>
<p class="hero-price-value">{e(price_range)}</p>
<p class="hero-price-note">自店の平均単価から計算した目安は{e(own_range)}です。くわしくは下の「報酬」で説明します。</p>
</div>
<p class="hero-promise">応募しても、すぐに契約にはなりません</p>
<p>まず面談で、報酬・費用・契約の中身を確認していただきます。契約するかどうかは、そのあとに決められます。</p>
<a class="btn btn-primary btn-wide" href="apply/">面談を申し込む</a>
<p class="hero-tel">お電話でも受け付けます：<a href="tel:{e(biz['phone'])}">{e(biz['phone'])}</a>（受付 {e(biz['phone_hours'])}）</p>
</section>
"""

    labels = {"busy": "繁忙期", "slow": "閑散期", "slow_half": "閑散期（半ばまで）", "none": ""}
    months = "".join(
        f'<li class="m-{state}"><span class="num">{m}月</span><small>{labels[state]}</small></li>'
        for m, state in job["demand"]["months"].items())
    work_time = "".join(f"<li>{e(w['label'])}：{e(w['value'])}</li>" for w in job["work_time"])
    s01 = section("01", "仕事の中身", "お客様宅でエアコンを分解して洗う仕事です", f"""
<p>{e(job['description'])}仕事です。</p>
<h3>作業時間の目安</h3>
<ul>{work_time}</ul>
<p class="note">出所：{e(job['work_time_source'])}</p>
<h3>依頼には波があります</h3>
<ul class="months">{months}</ul>
<p>繁忙期は{e(job['demand']['busy'])}、閑散期は{e(job['demand']['slow'])}です。閑散期は件数が減ることを、先にお伝えしておきます。</p>
<p class="note">出所：{e(job['demand']['source'])}</p>
""")

    s02 = section("02", "応募資格", "必要なのは普通自動車免許です", ul(data["requirements"]))

    stats = "".join(f"""<li class="stat">
<span class="stat-label">{e(a['label'])}</span>
<strong>{e(a['value'])}</strong>
{f'<span class="stat-detail">{e(a["detail"])}</span>' if a.get('detail') else ''}
<span class="stat-source">{e(source_label(a))}</span>
</li>""" for a in achievements)
    s03 = section("03", "募集の背景", "代表1名で受けてきた仕事を、一緒に担う人を探しています", f"""
<p>ハレノヒクリーンで作業している職人は、いまは代表1名です。そこで、最初の1人を募集します。</p>
<ul class="stats">{stats}</ul>
""")

    cards = "".join(f"""<li class="card">
<h3>{e(s['label'])}</h3>
<p class="calc">1日{s['per_day']}件 × 月{s['days']}日 ＝ {s['jobs']}件</p>
<p class="amount">月 {s['min_man']:g}万円〜{s['max_man']:g}万円</p>
</li>""" for s in pay["scenarios"])
    s04 = section("04", "報酬", "報酬は、単価と件数で決まります", f"""
<p class="formula">{e(pay['formula'])}</p>
<p>{e(pay['nature'])}。</p>
{rows([
    ("委託単価", f"{e(price_range)}<span class='cell-note'>（{e(source_label(price))}）</span>"),
    ("自店の目安", f"{e(own_range)}<span class='cell-note'>（{e(own['basis'])}）</span>"),
    ("支払い", e(pay['payment']['value'])),
])}
<p class="note">委託単価（グループ標準）と自店の目安は、幅が異なります。実際の単価は面談でご確認ください。</p>
<h3>働き方ごとの試算</h3>
<ul class="cards">{cards}</ul>
<ul class="note-list">
<li>グループ標準の単価（{e(price_range)}）で計算しています。</li>
<li>収入を約束するものではありません。</li>
<li>経費を引く前の金額です。</li>
<li>自店の目安（{e(own_range)}）は、この計算に使った単価より低いため、自店の目安で計算すると試算より少なくなります。</li>
</ul>
{apply_block()}
""")

    recent = next((a for a in achievements if a["key"] == "jobs_90d"), None)
    local = [f"在籍職人：{area['crew']}"]
    if recent:
        local.append(f"{recent['label']}：{recent['value']}（{site['area']}エリア）")
    s05 = section("05", "活動エリア", f"{area['summary']}が対応エリアです", f"""
<p>{e(area['cities'])}。</p>
<p class="note">出所：{e(area['source'])}</p>
<p>{e(area['assignment'])}。</p>
<h3>{e(site['area'])}エリアの今</h3>
{ul(local)}
""")

    s06 = section("06", "1日の流れ", "出社はなく、現場へ直接向かいます", f"""
{ul(data['day']['points'])}
<ol class="timeline">
<li>自宅から1件目の現場へ向かう</li>
<li>養生・分解・高圧洗浄・組み立て・動作確認</li>
<li>次の現場へ向かう（件数は自分で決めます）</li>
<li>最後の現場から直接帰宅する</li>
</ol>
<p class="note">1台ごとの作業時間の目安は「仕事の中身」をご覧ください。</p>
""")

    cost_rows = []
    for c in contract["costs"]:
        label = source_label(c) if "source" in c else ""
        note = f"<span class='cell-note'>（{e(label)}）</span>" if label else ""
        cost_rows.append((c["item"], f"{e(c['value'])}{note}"))
    s07 = section("07", "契約と費用", "雇用ではなく業務委託です。始める費用もここに書きます", f"""
{rows([("契約の形", e(contract['form'])), ("稼働日", e(contract['days'])), ("契約期間・終了", e(contract['term']))])}
<h3>始めるときの費用</h3>
{rows(cost_rows)}
<p class="note">{e(contract['tools_note'])}</p>
<h3>こんな方には向いていません</h3>
{ul(contract['not_for'], 'not-for')}
""")

    s08 = section("08", "応募から独り立ちまで", "面談、契約、研修の順に進みます", f"""
<ol class="steps">{''.join(f'<li>{e(step)}</li>' for step in data['flow'])}</ol>
<p>面談の方法は、申込フォームで希望を選べます（Zoom／電話／対面）。</p>
""")

    training = data["training"]
    s09 = section("09", "研修", "動画で学び、先輩の現場に同行します", f"""
{ul([training['online'], training['ride_along']])}
<p>研修費は{e(training['fee'])}</p>
{apply_block()}
""")

    s10 = section("10", "その先", "経験を積んだ先に、自分の店を持つ道もあります", ul(data["future"]))

    faq = "".join(f"<details><summary>{e(f['q'])}</summary><p>{e(f['a'])}</p></details>" for f in data["faq"])
    s11 = section("11", "よくある質問", "応募の前によくある質問", faq)

    rep = data["representative"]
    s12 = section("12", "代表あいさつ", f"代表の{biz['representative']}です", f"""
{''.join(f'<p>{e(p)}</p>' for p in rep['greeting'])}
<p>{e(rep['values_lead'])}</p>
{ul(rep['values'])}
""")

    guide = f"""<section class="block guide">
<h2>面談で、条件をひとつずつ確認しましょう</h2>
<p>応募しても、すぐに契約にはなりません。報酬や費用について気になることは、面談でそのままお尋ねください。</p>
<a class="btn btn-primary btn-wide" href="apply/">面談を申し込む</a>
<p class="hero-tel">お電話：<a href="tel:{e(biz['phone'])}">{e(biz['phone'])}</a>（受付 {e(biz['phone_hours'])}）</p>
</section>
"""

    operator = f"""<section class="block operator">
<h2>募集を行う事業者</h2>
{rows([
    ("店名", e(biz['name'])),
    ("代表", e(biz['representative'])),
    ("所在地", f"{e(biz['location'])}<span class='cell-note'>（{e(biz['location_note'])}）</span>"),
    ("電話", f"<a href='tel:{e(biz['phone'])}'>{e(biz['phone'])}</a><span class='cell-note'>（受付 {e(biz['phone_hours'])}）</span>"),
    ("公式サイト", f"<a href='{e(biz['website'])}'>{e(biz['website'])}</a>"),
    ("ページ更新日", jp_date(site['page_updated'])),
])}
</section>
"""

    body = "<main>\n" + hero + s01 + s02 + s03 + s04 + s05 + s06 + s07 + s08 + s09 + s10 + s11 + s12 + guide + operator + "</main>"
    title = f"{job['title']}の募集｜{site['area']}｜{biz['name']}"
    description = f"{site['area']}エリアで{job['title']}を募集しています。応募しても、すぐに契約にはなりません。"
    return layout(data, "index.html", title, description, body, jsonld=job_posting(data))


def render_apply(data):
    biz = data["business"]
    phone_message = f"お手数ですが、お電話でご連絡ください（{biz['phone']}）"
    body = f"""<main>
<section class="block">
<h1 class="page-title">面談の申し込み</h1>
<p>応募しても、すぐに契約にはなりません。まず面談で、報酬・費用・契約の中身を確認していただきます。</p>
<p class="tel-box">お電話でも受け付けます<a class="btn btn-tel btn-wide" href="tel:{e(biz['phone'])}">{e(biz['phone'])}</a><small>受付 {e(biz['phone_hours'])}</small></p>
<noscript><p class="form-status is-error">{e(phone_message)}</p></noscript>
<form id="apply-form" novalidate data-phone-message="{e(phone_message)}" data-phone="{e(biz['phone'])}">
<div class="field">
<label for="name">お名前<span class="req">必須</span></label>
<input id="name" name="name" type="text" autocomplete="name" required>
</div>
<div class="field">
<label for="contact">電話番号またはメールアドレス<span class="req">必須</span></label>
<input id="contact" name="contact" type="text" autocomplete="on" required>
</div>
<fieldset class="field">
<legend>希望する連絡方法<span class="req">必須</span></legend>
<label class="choice"><input type="radio" name="contact_method" value="電話" required>電話</label>
<label class="choice"><input type="radio" name="contact_method" value="メール">メール</label>
</fieldset>
<div class="field">
<label for="first_choice">面談の第1希望日時<span class="opt">任意</span></label>
<input id="first_choice" name="first_choice" type="datetime-local">
</div>
<fieldset class="field">
<legend>面談方法<span class="opt">任意</span></legend>
<label class="choice"><input type="radio" name="meeting_method" value="Zoom">Zoom</label>
<label class="choice"><input type="radio" name="meeting_method" value="電話">電話</label>
<label class="choice"><input type="radio" name="meeting_method" value="対面">対面</label>
</fieldset>
<div class="field">
<label for="note">質問・備考<span class="opt">任意</span></label>
<textarea id="note" name="note" rows="4"></textarea>
</div>
<div class="field">
<label class="choice"><input type="checkbox" name="adult" value="はい" required>18歳以上です<span class="req">必須</span></label>
<label class="choice"><input type="checkbox" name="privacy" value="同意する" required><span><a href="../privacy/">個人情報の取り扱い</a>に同意します</span><span class="req">必須</span></label>
</div>
<p id="form-status" class="form-status" role="alert" hidden></p>
<button class="btn btn-primary btn-wide" type="submit" disabled>面談を申し込む</button>
</form>
</section>
</main>
<script src="config.js"></script>
<script src="form.js"></script>"""
    return layout(data, "apply/index.html", f"面談の申し込み｜{biz['name']}",
                  f"{biz['name']}の業務委託の募集について、面談を申し込むページです。", body, apply_cta=False)


def render_privacy(data):
    biz, site = data["business"], data["site"]
    body = f"""<main>
<section class="block prose">
<h1 class="page-title">個人情報の取り扱い</h1>
<p>{e(biz['name'])}（代表 {e(biz['representative'])}）は、申込フォームやお電話でお預かりする個人情報を、次のとおり取り扱います。</p>
<h2>お預かりする情報</h2>
<p>お名前、電話番号またはメールアドレス、希望する連絡方法、18歳以上であることの確認、面談の希望日時、面談方法、質問・備考。</p>
<h2>使う目的</h2>
{ul(['面談の日程調整とご連絡', 'ご質問への回答', '業務委託契約に向けたご案内'])}
<h2>第三者への提供</h2>
<p>ご本人の同意がある場合と、法令に基づく場合を除き、第三者に提供しません。</p>
<h2>外部サービスの利用</h2>
<p>申込内容の受付や保管に外部のサービスを使う場合があります。その場合も、上の目的の範囲で取り扱います。</p>
<h2>管理</h2>
<p>お預かりした情報は、漏えいや紛失がないよう管理し、必要がなくなったものは消去します。</p>
<h2>確認・訂正・削除</h2>
<p>ご自身の情報の確認、訂正、削除をご希望の方は、下記までご連絡ください。</p>
<h2>お問い合わせ先</h2>
{rows([
    ("事業者", e(biz['name'])),
    ("所在地", e(biz['location'])),
    ("電話", f"<a href='tel:{e(biz['phone'])}'>{e(biz['phone'])}</a><span class='cell-note'>（受付 {e(biz['phone_hours'])}）</span>"),
    ("ページ更新日", jp_date(site['page_updated'])),
])}
<p class="back"><a href="../">募集ページに戻る</a></p>
</section>
</main>"""
    return layout(data, "privacy/index.html", f"個人情報の取り扱い｜{biz['name']}",
                  f"{biz['name']}の個人情報の取り扱いについて。", body)


# ---------- 実行 ----------

def build(data_path, out, today):
    data = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    terms = yaml.safe_load((GENERATOR / "terms.yml").read_text(encoding="utf-8"))
    check_data(data, today)

    # 送信先を設定した後に再ビルドしても消さないよう、config.js は既存のものを残す
    config = out / "apply" / "config.js"
    pages = {
        "index.html": render_index(data, today),
        "apply/index.html": render_apply(data),
        "privacy/index.html": render_privacy(data),
        "apply/form.js": (GENERATOR / "form.js").read_text(encoding="utf-8"),
        "apply/config.js": config.read_text(encoding="utf-8") if config.exists() else CONFIG_JS,
    }
    check_terms(pages, terms)
    check_numbers(pages, data)
    check_pages(pages, data)

    # 検査に通ってから書き出すので、失敗時に docs/ は変わらない
    for path, text in pages.items():
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    shutil.copy(GENERATOR / "style.css", out / "style.css")
    (out / ".nojekyll").touch()
    return sorted(pages) + ["style.css"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "sites" / "harenohiclean" / "data.yml")
    parser.add_argument("--out", type=Path, default=ROOT / "docs")
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    args = parser.parse_args()
    try:
        written = build(args.data, args.out, args.today)
    except BuildError as err:
        print(f"ビルド失敗: {err}", file=sys.stderr)
        return 1
    print(f"ビルド成功（NG語・数値・noindex・JobPosting の検査に合格）: {args.out}")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
