#!/usr/bin/env python3
"""
自動翻訳：content/ の日本語ファイルを元に、各言語のファイル（content/〇〇.en.json など）を埋める。

翻訳するのは次の所だけ。手で直した翻訳は、日本語が変わらない限りそのまま残す。
  - 翻訳が空欄・まだない（新しく足した作品・お知らせなど）
  - 翻訳が日本語のまま（かなが入っている）
  - 前回翻訳したときから日本語の文章が変わった

翻訳サービスは、GitHub の Secrets に入っているキーで決まる。
  ANTHROPIC_API_KEY があれば Claude、なければ DEEPL_API_KEY で DeepL。どちらもなければ何もしない。
  （テスト用に TRANSLATE_PROVIDER=fake で「[en]日本語」のような偽の翻訳もできる）

使い方：python3 tools/auto_translate.py   （リポジトリのルートで）
"""
import copy, hashlib, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, "content")
STATE = os.path.join(ROOT, "tools", "i18n-sources.json")  # 何の日本語から翻訳したかの記録

LANG_NAMES = {"en": "English", "zh": "Simplified Chinese", "ko": "Korean"}

# ----- 翻訳する項目 -----
# トップページ：この名前の項目は全部翻訳（トップの index.html と同じ）
HOME_KEYS = {"title", "lead", "sleep", "wake", "hint", "body", "services", "conds", "big", "label", "say",
             "imageAlt", "t", "s", "st", "plat", "tagline", "p", "copy", "contact"}
# 見積りページ：この場所だけ翻訳（estimate/index.html と同じ。* はリストの各要素）
EST_PATHS = {
    "hero.title", "hero.lead", "hero.badges", "hero.gen.say", "steps.*.title", "steps.*.lead",
    "scales.*.name", "scales.*.tag", "scales.*.lines", "sources", "sendNote", "bar.caption", "bar.empty",
    "bar.button", "bar.mutters.*.text", "works.title", "works.lead", "works.items.*.title", "works.items.*.meta",
    "works.items.*.desc", "works.items.*.links.*.label", "terms.title", "terms.lead", "terms.items.*.k",
    "terms.items.*.v", "terms.notes.*.title", "terms.notes.*.body", "footer",
    "items.*.name", "items.*.unit.s", "items.*.unit.m", "items.*.unit.l", "items.*.plans.*.label",
    "items.*.can", "items.*.ng", "items.*.at",
}
FILES = [
    ("site", ["en", "zh", "ko"], "home"),
    ("home", ["en", "zh", "ko"], "home"),
    ("games", ["en", "zh", "ko"], "home"),
    ("topics", ["en", "zh", "ko"], "home"),
    ("estimate-page", ["en"], "est"),
    ("estimate", ["en"], "est"),
]
# げんちゃんのセリフ（口調を変えるため翻訳サービスに伝える）
VOICE_KEYS = {"say", "sleep", "wake", "text", "empty"}

KANA = re.compile(r"[぀-ヿ]")


def is_tr(kind, path, key):
    if kind == "home":
        return key in HOME_KEYS
    return path in EST_PATHS


def norm(path):
    return re.sub(r"\[[^\]]*\]", ".*", path).replace("..", ".").lstrip(".")


def pair_key(x):
    if isinstance(x, dict):
        if x.get("id") not in (None, ""):
            return "id=%s:%s" % (x.get("type", ""), x["id"])
        if x.get("d") not in (None, ""):
            return "d=%s" % x["d"]
    return None


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


# ----- 日本語版の形に合わせて翻訳ファイルを組み直しつつ、翻訳が必要な所を集める -----
class Slot:
    """翻訳待ちの1項目。あとで value に訳が入る"""
    def __init__(self, ja, cur, sid, path, voice, prev):
        self.ja, self.cur, self.sid, self.path, self.voice, self.prev = ja, cur, sid, path, voice, prev
        self.value = None


def build(kind, ja, loc, path, sid, slots, state, new_state):
    """ja の形で新しい翻訳データを作る。翻訳が要る所は Slot にして slots に積む"""
    if isinstance(ja, dict):
        loc = loc if isinstance(loc, dict) else {}
        out = {}
        for k, v in ja.items():
            p = (path + "." if path else "") + k
            s = sid + "." + k
            if is_tr(kind, norm(p), k) and not isinstance(v, dict):
                out[k] = leaf(v, loc.get(k), s, p, k, slots, state, new_state)
            else:
                out[k] = build(kind, v, loc.get(k), p, s, slots, state, new_state)
        return out
    if isinstance(ja, list):
        if not ja or not all(isinstance(x, dict) for x in ja):
            return copy.deepcopy(ja)
        loc = loc if isinstance(loc, list) else []
        used, out, seen = set(), [], {}
        for i, b in enumerate(ja):
            k = pair_key(b)
            l = None
            if k:
                for j, x in enumerate(loc):
                    if j not in used and pair_key(x) == k:
                        l = x; used.add(j); break
                n = seen.get(k, 0); seen[k] = n + 1
                s = "%s[%s#%d]" % (sid, k, n)
            else:
                if i < len(loc) and isinstance(loc[i], dict) and loc[i].get("type", "") == b.get("type", ""):
                    l = loc[i]
                s = "%s[%d]" % (sid, i)
            out.append(build(kind, b, l, path + "[]", s, slots, state, new_state))
        return out
    return copy.deepcopy(ja)


def leaf(ja, loc, sid, path, key, slots, state, new_state):
    """翻訳する1項目（文字列、または文字列のリスト）"""
    voice = key in VOICE_KEYS
    if isinstance(ja, list):
        ja = [x for x in ja if isinstance(x, str) and x.strip()]
        if not ja:
            return []
        cur = [x for x in loc if isinstance(x, str)] if isinstance(loc, list) else []
    elif isinstance(ja, str):
        if not ja.strip():
            return ""
        cur = loc if isinstance(loc, str) else ""
    else:
        return copy.deepcopy(ja)
    if needs(ja, cur, sid, state):
        slot = Slot(ja, cur, sid, path, voice, state.get(sid))
        slots.append(slot)
        new_state[sid] = digest(ja)
        return slot
    new_state[sid] = state.get(sid) or digest(ja)
    return cur


def digest(v):
    return hashlib.sha1(json.dumps(v, ensure_ascii=False).encode()).hexdigest()[:12]


def needs(ja, cur, sid, state):
    if isinstance(ja, list):
        if len(cur) != len(ja) or not all(x.strip() for x in cur):
            return True
        if any(KANA.search(x) for x in cur):
            return True
    else:
        if not cur.strip():
            return True
        if KANA.search(cur):  # 日本語のまま
            return True
    rec = state.get(sid)
    return rec is not None and rec != digest(ja)  # 前回翻訳したときから日本語が変わった


def finalize(x):
    if isinstance(x, Slot):
        return x.value
    if isinstance(x, dict):
        return {k: finalize(v) for k, v in x.items()}
    if isinstance(x, list):
        return [finalize(v) for v in x]
    return x


# ----- 翻訳サービス -----
STYLE = """You translate text for the website of G3 (GenGorouGames), a small, playful indie game team in Tokyo.
Rules:
- Natural, friendly, concise {lang}. Not stiff. Keep the playful tone.
- Lines marked VOICE are spoken by the mascot "げんちゃん": sleepy, grumpy, deadpan, very short, casual speech
  (English: casual; Chinese: casual 口语; Korean: 반말). Keep the "…" pauses.
- Other site text: polite but light (Korean: 해요체).
- Keep markup exactly: text wrapped in *asterisks* stays wrapped in *asterisks* (move them to the matching words);
  keep line breaks (\\n) and blank lines; keep placeholders like {{mail}} unchanged; keep URLs, emails, product names.
- Fixed names: がむしゃらギルド = "Scrappy Guild" (in every language). げんちゃん = "Genchan" (English, Chinese), "겐짱" (Korean).
  G3 / GenGorouGames / Final Tower Ⅶ / MakeFALL / Watch / Unity / Steam stay as is. ゲンゴロウゲームズ = GenGorouGames (Korean: 겐고로게임즈).
- Prices are in Japanese yen; don't convert numbers.
Return ONLY a JSON object mapping each id to its translation, nothing else."""


def translate_claude(items, lang, key):
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    out = {}
    for chunk in [items[i:i + 60] for i in range(0, len(items), 60)]:
        payload = {str(i): ("[VOICE] " if v else "") + "[" + p + "] " + t for i, (t, p, v) in chunk}
        body = {
            "model": model, "max_tokens": 8000,
            "system": STYLE.format(lang=LANG_NAMES[lang]),
            "messages": [{"role": "user", "content":
                          "Translate the Japanese text in each value into %s. The [bracketed] prefix is only context "
                          "(where the text appears) — do not include it in the output.\n\n%s"
                          % (LANG_NAMES[lang], json.dumps(payload, ensure_ascii=False, indent=1))}],
        }
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                              "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            res = json.load(r)
        text = "".join(b.get("text", "") for b in res.get("content", []))
        m = re.search(r"\{.*\}", text, re.S)
        got = json.loads(m.group(0)) if m else {}
        for i, _ in chunk:
            if isinstance(got.get(str(i)), str) and got[str(i)].strip():
                out[i] = got[str(i)].strip()
    return out


def translate_deepl(items, lang, key):
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    target = {"en": "EN-US", "zh": "ZH-HANS", "ko": "KO"}[lang]
    gen = "겐짱" if lang == "ko" else "Genchan"

    def enc(t):  # 強調・改行・名前を壊されないようにタグにする
        t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        t = re.sub(r"\*([^*\n]+)\*", r"<em>\1</em>", t)
        t = t.replace("{mail}", "<x>{mail}</x>").replace("がむしゃらギルド", "<x>Scrappy Guild</x>")
        t = t.replace("げんちゃん", "<x>%s</x>" % gen)
        return t.replace("\n", "<br/>")

    def dec(t):
        t = re.sub(r"<br\s*/?>", "\n", t)
        t = re.sub(r"</?x>", "", t)
        t = re.sub(r"<em>(.*?)</em>", r"*\1*", t)
        return t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

    out = {}
    for chunk in [items[i:i + 40] for i in range(0, len(items), 40)]:
        body = {"text": [enc(t) for _, (t, p, v) in chunk], "source_lang": "JA", "target_lang": target,
                "tag_handling": "xml", "ignore_tags": ["x"]}
        req = urllib.request.Request("https://%s/v2/translate" % host, data=json.dumps(body).encode(),
                                     headers={"Authorization": "DeepL-Auth-Key " + key,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.load(r)
        for (i, _), tr in zip(chunk, res.get("translations", [])):
            out[i] = dec(tr["text"]).strip()
    return out


def translate_fake(items, lang, key):
    return {i: "[%s]%s" % (lang, hashlib.sha1(t.encode()).hexdigest()[:8]) for i, (t, p, v) in items}


def provider():
    forced = os.environ.get("TRANSLATE_PROVIDER")
    if forced == "fake":
        return "fake", translate_fake, ""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "Claude", translate_claude, os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("DEEPL_API_KEY"):
        return "DeepL", translate_deepl, os.environ["DEEPL_API_KEY"]
    return None, None, None


# ----- 本体 -----
def main():
    state_all = load(STATE) or {}
    name, fn, key = provider()
    changed, done, failed = [], 0, 0
    new_state_all = {}

    for base, langs, kind in FILES:
        ja = load(os.path.join(CONTENT, base + ".json"))
        if ja is None:
            continue
        for lang in langs:
            path = os.path.join(CONTENT, "%s.%s.json" % (base, lang))
            loc = load(path)
            sk = "%s.%s" % (base, lang)
            state = state_all.get(sk, {})
            new_state, slots = {}, []
            built = build(kind, ja, loc, "", "", slots, state, new_state)

            # 1項目ずつ（リストは1行ずつ）翻訳に出す
            items = []
            for si, sl in enumerate(slots):
                for li, t in enumerate(sl.ja if isinstance(sl.ja, list) else [sl.ja]):
                    items.append(((si, li), (t, sl.path, sl.voice)))
            res = {}
            if items and fn:
                try:
                    flat = fn([(n, it[1]) for n, it in enumerate(items)], lang, key)
                    res = {items[n][0]: v for n, v in flat.items()}
                except Exception as e:  # 翻訳サービスのエラー：今回は見送り（次の保存で再挑戦）
                    print("::warning::%s の %s 翻訳に失敗：%s" % (base, lang, e))

            for si, sl in enumerate(slots):
                parts = sl.ja if isinstance(sl.ja, list) else [sl.ja]
                got = [res.get((si, li)) for li in range(len(parts))]
                if all(isinstance(g, str) and g for g in got):
                    sl.value = got if isinstance(sl.ja, list) else got[0]
                    done += 1
                else:
                    # 翻訳できなかった：前の翻訳（空ならサイトでは日本語が出る）のまま。記録も前のままにして、次回また翻訳する
                    sl.value = sl.cur
                    failed += 1
                    if sl.prev is None:
                        new_state.pop(sl.sid, None)
                    else:
                        new_state[sl.sid] = sl.prev

            built = finalize(built)
            new_state_all[sk] = new_state
            if built != loc:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(built, f, ensure_ascii=False, indent=2)
                    f.write("\n")
                changed.append(os.path.relpath(path, ROOT))

    if new_state_all != state_all:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(new_state_all, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")

    print("翻訳サービス：%s / 翻訳した項目：%d / 翻訳できなかった項目：%d" % (name or "なし", done, failed))
    if failed and not fn:
        print("::warning::翻訳が必要な項目が %d 個ありますが、ANTHROPIC_API_KEY も DEEPL_API_KEY も設定されていません" % failed)
    for c in changed:
        print("更新：" + c)


if __name__ == "__main__":
    main()
