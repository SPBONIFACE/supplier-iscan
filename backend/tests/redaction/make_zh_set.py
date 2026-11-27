"""Writes the Chinese evaluation set (#100) to `evalset/zh/`. Run once, before any detection change;
the two files it writes are then frozen (never tuned on, never regenerated).

    uv run python -m tests.redaction.make_zh_set

Synthetic only: every person is a random combination of common surnames and given-name characters
or syllables, every company and place is invented. Fixed seed, so the output is reproducible.
Ids with `id % 10 < 3` are the tuning part, the others the report part (as in `evalset/main`).

`names.jsonl`: {id, lang: "zh", script, ntype, ctx, text, spans, scripts, title_spans}
    `script` is "han" or "latin" (the script of the name; "both" for a name written twice).
    `scripts` gives the script of each span; `title_spans` are title words that must stay readable.
`nonperson.jsonl`: {id, lang: "zh", kind, ctx, text, items, suzhou}
    `items` are the character spans of the companies, places and product words (none is a person);
    `suzhou` marks the cases of the invented "Suzhou Zi Jin Plastic Co., Ltd" that must stay as is.
"""

# ruff: noqa: E501, UP031, B023, S311
# One-off data generator (fixed seed, never used at run time): long literal lists, `%` templates and
# `random` (not for security) are deliberate.

import json
import random
from pathlib import Path

OUT = Path(__file__).parent / "evalset" / "zh"
rng = random.Random(100)

SURNAMES = list(
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何林高罗郑梁谢宋唐许韩冯邓曹彭曾萧田董潘袁蔡蒋余杜叶程苏魏吕丁任"
    "卢姚沈钟姜崔谭陆范汪廖石金韦贾夏付方邹熊白孟秦邱侯江尹薛段雷黎史陶贺顾毛郝龚邵万钱严赖洪武莫孔"
)
COMPOUND = "欧阳 司马 上官 诸葛 慕容 皇甫 尉迟 公孙 令狐 东方 夏侯 长孙 宇文 端木 南宫".split()
GIVEN = list(
    "伟芳娜敏静丽强磊军洋勇艳杰娟涛明超霞平刚嘉怡欣雅婷慧倩鹏浩宇轩子涵思琪俊凯晨阳博文昊天宏志远"
    "建国华春秋冬雪梅兰竹菊海波涵萱梓桐彤诗悦佳琳瑶薇娅琴凤玲倩彬斌翔飞龙虎豪昌盛荣光辉煌"
)
TRAD_SURNAMES = list(
    "張陳劉楊黃趙吳周徐孫馬朱胡郭林高羅鄭梁謝宋唐許韓馮鄧曹彭曾蕭董潘袁蔡蔣葉程蘇魏呂盧姚鍾姜崔譚陸"
    "廖韋賈鄒熊閻雷龍黎賀顧龔邵萬錢嚴賴"
)
TRAD_GIVEN = list(
    "偉芳娜敏靜麗強磊軍勇豔傑娟濤明超霞剛嘉怡欣雅婷慧倩穎鵬浩宇軒涵思琪俊凱晨陽博文昊天宏志遠建國華"
    "春秋雪梅蘭竹海萱梓桐彤詩悅佳琳瑤薇雯鳳玲彬斌翔飛龍豪榮輝"
)
MINORITY_GIVEN = (
    "阿依古丽 艾尔肯 古丽娜 吐尔逊 买买提 热依扎 阿卜杜 努尔 玛依拉 帕提古丽 木拉提 赛力克 巴特尔 其木格 扎西 多杰 "
    "格桑 旺堆 卓玛 次仁 阿木尔 孜热 迪丽努尔 加依娜 哈尔哈什 托合提 艾买尔 热合曼 库尔班 阿不拉 祖木热提 斯琴 "
    "乌力吉 苏布道 那顺 满都拉"
).split()

PIN_SUR = (
    "Zhang Wang Li Liu Chen Yang Huang Zhao Wu Zhou Xu Sun Ma Zhu Hu Guo He Lin Gao Luo Zheng Liang Xie "
    "Song Tang Han Feng Deng Cao Peng Zeng Xiao Tian Dong Pan Yuan Cai Jiang Yu Du Ye Cheng Su Wei Lu "
    "Ding Ren Shen Zhong Yao Cui Tan Fan Wang Liao Shi Jin Xia Fu Fang Zou Xiong Bai Meng Qin Hou"
).split()
PIN_GIVEN = (
    "Wei Fang Na Min Jing Li Qiang Lei Jun Yang Yong Jie Juan Tao Ming Chao Xia Ping Gang Jia Yi Xin Ya "
    "Ting Hui Qian Peng Hao Yu Xuan Zi Han Si Qi Kai Chen Bo Wen Hong Zhi Yuan Hua Chun Xue Mei Lan "
    "Shan Yan Lin Fei Long Hu Bin Xiang Rong Guang"
).split()
HK_SUR = "Chan Wong Lee Cheung Lau Ng Leung Chow Yeung Tsang Fung Ho Lam Kwok Yip Tam Chu Mak Szeto Poon".split()
HK_GIVEN = (
    "Tai Man Siu Ming Ka Fai Wing Yan Chi Keung Kwok Wai Man Ho Hing Fung Kin Lok Yuk Lam Sau Mei Pui Shan "
    "Ka Yee Tsz Ching Wai Lun Ching Yin Chun Kit Hoi Ting Kam Wah Sze Wing Kai Cheuk"
).split()
TW_SUR = "Lin Chen Huang Chang Lee Wang Wu Liu Tsai Yang Hsu Cheng Hsieh Kuo Chiu Tseng Liao Lai Hsiao".split()
TW_GIVEN = (
    "Yu Ting Chia Hao Mei Ling Chih Ming Pei Shan Wei Chen Yi Hsuan Shu Fen Cheng Han Hsiu Ying Ya Ting "
    "Chun Yi Kuan Lin Szu Yuan Jui Hsiang Ming Hui Tzu Chieh Po Wen"
).split()

CITIES = "上海 北京 苏州 无锡 宁波 东莞 佛山 成都 武汉 青岛 天津 厦门 杭州 常州 昆山".split()
CITIES_EN = "Shanghai Beijing Suzhou Wuxi Ningbo Dongguan Foshan Chengdu Wuhan Qingdao Tianjin Xiamen".split()
DEPTS = "销售部 采购部 质量部 客户服务部 财务部 物流部 技术部 市场部".split()
DEPTS_EN = [
    "Sales Office",
    "Purchasing",
    "Quality Department",
    "Customer Service",
    "Logistics",
    "Finance",
]

used: set[str] = set()


def unique(make) -> str:  # type: ignore[no-untyped-def]
    for _ in range(1000):
        value = make()
        if value not in used and "Suzhou Zi Jin Plastic" not in value:
            used.add(value)
            return str(value)
    raise RuntimeError("pool exhausted")


# --- name tokens: (text, [name spans], [title spans], scripts) ------------------------------------
Token = tuple[str, list[tuple[int, int]], list[tuple[int, int]], list[str]]


def given_han(pool: list[str]) -> str:
    return "".join(rng.choice(pool) for _ in range(rng.choice((1, 2))))


def han_plain(kind: str) -> str:
    if kind == "h3":
        return rng.choice(SURNAMES) + "".join(rng.choice(GIVEN) for _ in range(2))
    if kind == "h2":
        return rng.choice(SURNAMES) + rng.choice(GIVEN)
    if kind == "hc":
        return rng.choice(COMPOUND) + given_han(GIVEN)
    if kind == "ht":
        return rng.choice(TRAD_SURNAMES) + "".join(
            rng.choice(TRAD_GIVEN) for _ in range(rng.choice((1, 2)))
        )
    if kind == "hd":
        return rng.choice(MINORITY_GIVEN) + "·" + rng.choice(MINORITY_GIVEN)
    raise ValueError(kind)


HAN_TITLES_AFTER = [
    "经理",
    "总",
    "先生",
    "女士",
    "博士",
    "老师",
    "总监",
    "主任",
    "工程师",
    "董事长",
]
HAN_TITLES_BEFORE = ["总经理", "经理", "董事长", "总监", "主任", "工程师", "博士", "教授"]


def han_token(kind: str, *, split: bool = False) -> Token:
    if kind == "hT":
        shape = rng.choice(("sur_after", "sur_after", "full_after", "title_before"))
        if shape == "sur_after":
            name = unique(lambda: rng.choice(SURNAMES))
            title = rng.choice(HAN_TITLES_AFTER)
            return name + title, [(0, 1)], [(1, 1 + len(title))], ["han"]
        base = unique(lambda: han_plain(rng.choice(("h3", "h2", "hc"))))
        if shape == "full_after":
            title = rng.choice(HAN_TITLES_AFTER)
            return base + title, [(0, len(base))], [(len(base), len(base) + len(title))], ["han"]
        title = rng.choice(HAN_TITLES_BEFORE)
        return title + base, [(len(title), len(title) + len(base))], [(0, len(title))], ["han"]
    name = unique(lambda: han_plain(kind))
    if split:
        cut = 2 if kind == "hc" else (name.index("·") + 1 if kind == "hd" else 1)
        text = name[:cut] + "\n" + name[cut:]
        return text, [(0, len(text))], [], ["han"]
    return name, [(0, len(name))], [], ["han"]


def latin_plain(kind: str) -> str:
    if kind == "rfg":
        given = "".join(rng.choice(PIN_GIVEN) for _ in range(rng.choice((1, 2)))).capitalize()
        return f"{rng.choice(PIN_SUR)} {given}"
    if kind == "rgf":
        given = "".join(rng.choice(PIN_GIVEN) for _ in range(rng.choice((1, 2)))).capitalize()
        return f"{given} {rng.choice(PIN_SUR)}"
    if kind == "rcaps":
        given = "".join(rng.choice(PIN_GIVEN) for _ in range(rng.choice((1, 2)))).capitalize()
        sur = rng.choice(PIN_SUR)
        return rng.choice(
            (
                f"{sur.upper()} {given}",
                f"{sur.upper()} {given}",
                f"{sur.upper()} {given.upper()}",
                f"{given} {sur.upper()}",
                f"{sur.lower()} {given.lower()}",
            )
        )
    if kind == "rhk":
        given = " ".join(rng.choice(HK_GIVEN).capitalize() for _ in range(2))
        name = f"{rng.choice(HK_SUR)} {given}"
        return rng.choice((name, name, name.upper(), name.replace(" ", "", 0).title()))
    if kind == "rtw":
        given = "-".join([rng.choice(TW_GIVEN).capitalize(), rng.choice(TW_GIVEN).lower()])
        name = f"{rng.choice(TW_SUR)} {given}"
        return rng.choice(
            (
                name,
                name,
                name.replace("-", " "),
                name.replace("-", ""),
                f"{given} {rng.choice(TW_SUR)}",
            )
        )
    raise ValueError(kind)


LATIN_TITLES = [
    ("Mr. ", "", "mr"),
    ("Mr ", "", "mr"),
    ("Ms. ", "", "mr"),
    ("Dr. ", "", "mr"),
    ("Dr ", "", "mr"),
    ("Manager ", "", "role"),
    ("Director ", "", "role"),
    ("Engineer ", "", "role"),
    ("Prof. ", "", "mr"),
    ("Mrs. ", "", "mr"),
]


def latin_token(kind: str, *, split: bool = False) -> Token:
    if kind == "rT":
        shape = rng.choice(("mr_full", "mr_full", "role_sur", "role_sur", "after"))
        if shape == "role_sur":
            sur = unique(lambda: rng.choice(PIN_SUR) + rng.choice(("", " ", "  ")).strip())
            head = rng.choice(
                ("Manager ", "Director ", "General Manager ", "Engineer ", "Mr. ", "Ms. ")
            )
            return head + sur, [(len(head), len(head) + len(sur))], [(0, len(head) - 1)], ["latin"]
        name = unique(lambda: latin_plain(rng.choice(("rfg", "rgf", "rhk"))))
        if shape == "after":
            tail = rng.choice(
                (", Manager", ", Director", ", Sales Manager", ", Purchasing Manager")
            )
            return (
                name + tail,
                [(0, len(name))],
                [(len(name) + 2, len(name) + len(tail))],
                ["latin"],
            )
        head = rng.choice(("Mr. ", "Mr ", "Ms. ", "Dr. ", "Dr ", "Prof. ", "Mrs. "))
        return head + name, [(len(head), len(head) + len(name))], [(0, len(head) - 1)], ["latin"]
    name = unique(lambda: latin_plain(kind))
    if split and " " in name:
        cut = name.index(" ")
        text = name[:cut] + "\n" + name[cut + 1 :]
        return text, [(0, len(text))], [], ["latin"]
    return name, [(0, len(name))], [], ["latin"]


# --- frames -------------------------------------------------------------------------------------
def city() -> str:
    return rng.choice(CITIES)


def frame_han(ctx: str, tokens: list[Token]) -> str:
    """Frames with `{0}`, `{1}`... for the name tokens; returns the template."""
    n = len(tokens)
    if ctx == "signature":
        return rng.choice(
            [
                "此致\n敬礼\n{0}\n" + rng.choice(DEPTS),
                "顺祝商祺！\n{0}\n" + rng.choice(DEPTS) + "\n" + city() + "办事处",
                "谢谢！\n{0}\n" + rng.choice(DEPTS),
            ]
        )
    if ctx == "contact":
        return rng.choice(
            [
                "联系人：{0}\n地点：" + city(),
                "负责人：{0}\n地点：" + city(),
                "联系人：{0}　电子邮件见网站",
                "Contact: {0}\nLocation: " + rng.choice(CITIES_EN),
            ]
        )
    if ctx == "list":
        lines = "\n".join("- {%d}" % i for i in range(n))
        return rng.choice(["团队：\n" + lines, lines, "人员名单\n" + lines])
    if ctx == "prose":
        return rng.choice(
            [
                "昨天{0}与我们的仓库确认了交货日期。",
                "审计报告在季度末前由{0}签字批准。",
                "根据{0}的说明，样品将于下周寄出，运费由买方承担。",
                "上个月，{0}参观了我们位于" + city() + "的工厂，并讨论了包装规格。",
                "我们的代表{0}将在周三回复您的询价。",
            ]
        )
    if ctx == "table":
        row = (
            "| "
            + str(rng.randint(1000, 9999))
            + " | {0} | "
            + rng.choice(["已发货", "待处理", "已确认"])
            + " | "
            + f"{rng.randint(1, 9)}月{rng.randint(1, 28)}日 |"
        )
        if rng.random() < 0.5:
            return "| 编号 | 姓名 | 状态 | 日期 |\n" + row
        return row
    if ctx == "split":
        return rng.choice(
            [
                "三月份该档案由{0}在发货前处理。",
                "联系人：{0}\n地点：" + city(),
                "报价单由{0}整理并发送给客户。",
            ]
        )
    if ctx == "nextline":
        return rng.choice(
            ["联系人：\n{0}\n地点：" + city(), "负责人\n{0}\n" + rng.choice(DEPTS), "签名：\n{0}\n"]
        )
    if ctx == "alone":
        return rng.choice(
            [
                "产品目录第三版\n{0}\n" + rng.choice(DEPTS),
                "欢迎访问供应商门户\n{0}\n" + city(),
                "{0}",
            ]
        )
    if ctx == "page":
        return rng.choice(
            [
                "关于我们 | About us\nWe supply closures and caps worldwide. 总部设在"
                + city()
                + "，联系人{0}，欢迎来电。",
                "Product range: PET 28/410 caps\n产品咨询请联系 {0} (Sales)\nISO 9001 certified plant in "
                + rng.choice(CITIES_EN),
                "联系我们\nContact us today! 客户经理：{0}\n地址：" + city() + "市工业园区",
            ]
        )
    raise ValueError(ctx)


def frame_latin(ctx: str, tokens: list[Token]) -> str:
    n = len(tokens)
    if ctx == "signature":
        return rng.choice(
            [
                "Kind regards,\n{0}\n" + rng.choice(DEPTS_EN),
                "Best regards\n{0}\n"
                + rng.choice(DEPTS_EN)
                + "\n"
                + rng.choice(CITIES_EN)
                + " office",
                "Thank you,\n{0}\n" + rng.choice(DEPTS_EN),
            ]
        )
    if ctx == "contact":
        return rng.choice(
            [
                "Contact: {0}\nLocation: " + rng.choice(CITIES_EN),
                "Contact person: {0}, " + rng.choice(CITIES_EN),
                "联系人：{0}\n地点：" + city(),
            ]
        )
    if ctx == "list":
        lines = "\n".join("- {%d}" % i for i in range(n))
        return rng.choice(["Team:\n" + lines, lines, "Participants\n" + lines])
    if ctx == "prose":
        return rng.choice(
            [
                "Yesterday {0} confirmed the delivery date with our warehouse.",
                "The audit report was approved and signed by {0} before the end of the quarter.",
                "According to {0}, the samples will be sent next week at the buyer's cost.",
                "Last month {0} visited our plant in "
                + rng.choice(CITIES_EN)
                + " and reviewed the packaging specification.",
            ]
        )
    if ctx == "table":
        row = (
            "| "
            + str(rng.randint(1000, 9999))
            + " | {0} | "
            + rng.choice(["Shipped", "Pending", "Confirmed"])
            + f" | {rng.randint(1, 28)} May |"
        )
        if rng.random() < 0.5:
            return "| No. | Supplier | Status | Date |\n" + row
        return row
    if ctx == "split":
        return rng.choice(
            [
                "In March the file was handled by {0} before shipment.",
                "Quotation prepared by {0} for the customer.",
                "Contact: {0}\nLocation: " + rng.choice(CITIES_EN),
            ]
        )
    if ctx == "nextline":
        return rng.choice(
            [
                "Contact:\n{0}\nLocation: " + rng.choice(CITIES_EN),
                "Signed by\n{0}\n" + rng.choice(DEPTS_EN),
                "Name:\n{0}\n",
            ]
        )
    if ctx == "alone":
        return rng.choice(
            [
                "Product catalogue, third edition\n{0}\n" + rng.choice(DEPTS_EN),
                "Welcome to the supplier portal\n{0}\n" + rng.choice(CITIES_EN),
                "{0}",
            ]
        )
    if ctx == "page":
        return rng.choice(
            [
                "关于我们 | About us\nSales contact: {0}, 欢迎来电。\n总部设在" + city(),
                "产品目录 Product range\n联系人 Contact: {0}\nISO 9001 certified plant in "
                + rng.choice(CITIES_EN),
                "联系我们\nContact us today! Account manager {0}\n地址：" + city() + "市工业园区",
            ]
        )
    raise ValueError(ctx)


def build(
    template: str, tokens: list[Token]
) -> tuple[str, list[list[int]], list[str], list[list[int]]]:
    text = ""
    spans: list[list[int]] = []
    scripts: list[str] = []
    titles: list[list[int]] = []
    rest = template
    for index, (value, name_spans, title_spans, token_scripts) in enumerate(tokens):
        marker = "{%d}" % index
        position = rest.index(marker)
        text += rest[:position]
        base = len(text)
        text += value
        spans.extend([base + a, base + b] for a, b in name_spans)
        scripts.extend(token_scripts)
        titles.extend([base + a, base + b] for a, b in title_spans)
        rest = rest[position + len(marker) :]
    text += rest
    return text, spans, scripts, titles


CONTEXTS = ["signature", "contact", "list", "prose", "table", "split", "nextline", "alone", "page"]

HAN_TYPES = {"h3": 52, "h2": 44, "hc": 34, "hd": 32, "ht": 34, "hT": 44}
LATIN_TYPES = {"rfg": 40, "rgf": 36, "rcaps": 30, "rhk": 32, "rtw": 32, "rT": 44}


def make_names() -> list[dict]:  # type: ignore[type-arg]
    items: list[dict] = []  # type: ignore[type-arg]
    for han, quota in ((True, HAN_TYPES), (False, LATIN_TYPES)):
        for ntype, count in quota.items():
            titled = ntype in ("hT", "rT")
            contexts = [c for c in CONTEXTS if not (titled and c == "split")]
            order = [contexts[i % len(contexts)] for i in range(count)]
            rng.shuffle(order)
            for ctx in order:
                size = rng.choice((2, 3)) if ctx == "list" else 1
                make = han_token if han else latin_token
                tokens = [make(ntype, split=(ctx == "split")) for _ in range(size)]
                frame = (frame_han if han else frame_latin)(ctx, tokens)
                text, spans, scripts, titles = build(frame, tokens)
                items.append(
                    {
                        "lang": "zh",
                        "script": "han" if han else "latin",
                        "ntype": ntype,
                        "ctx": ctx,
                        "text": text,
                        "spans": spans,
                        "scripts": scripts,
                        "title_spans": titles,
                    }
                )
    # the same person written twice, once in Han and once romanised
    for _ in range(24):
        sur_index = rng.randrange(len(SURNAMES))
        han_name = unique(
            lambda: SURNAMES[sur_index] + "".join(rng.choice(GIVEN) for _ in range(2))
        )
        latin_name = unique(
            lambda: (
                rng.choice(PIN_SUR)
                + " "
                + "".join(rng.choice(PIN_GIVEN) for _ in range(2)).capitalize()
            )
        )
        text, spans, scripts, _titles = build(
            rng.choice(
                [
                    "{0} ({1}) is our contact for the " + city() + " plant.",
                    "联系人：{0}\nContact: {1}\n地点：" + city(),
                    "{0}\n{1}\n" + rng.choice(DEPTS),
                ]
            ),
            [
                (han_name, [(0, len(han_name))], [], ["han"]),
                (latin_name, [(0, len(latin_name))], [], ["latin"]),
            ],
        )
        items.append(
            {
                "lang": "zh",
                "script": "both",
                "ntype": "dual",
                "ctx": "dual",
                "text": text,
                "spans": spans,
                "scripts": scripts,
                "title_spans": [],
            }
        )
    return items


# --- non-person items ---------------------------------------------------------------------------
HAN_ADJ = "紫金 华兴 恒达 鑫源 宏图 瑞丰 嘉禾 天成 远景 东盛 凯旋 汇通 金桥 明珠 泰和 瀚海 龙腾 博远".split()
HAN_INDUSTRY = (
    "塑料 包装 精密制造 金属制品 化工 印刷 模具 瓶盖 复合材料 机械 玻璃制品 食品 物流".split()
)
HAN_FORM = ["有限公司", "股份有限公司", "集团有限公司", "有限责任公司"]
LATIN_FORM = ["Co., Ltd", "Co., Ltd.", "Co. Ltd", "Limited", "Ltd", "Pte Ltd", "Group Co., Ltd"]
PIN_ADJ = "Zi Jin|Hua Xing|Heng Da|Xin Yuan|Hong Tu|Rui Feng|Jia He|Tian Cheng|Yuan Jing|Dong Sheng|Hui Tong|Jin Qiao|Ming Zhu|Tai He|Han Hai|Long Teng|Bo Yuan".split(
    "|"
)
PIN_INDUSTRY = "Plastic|Packaging|Precision Manufacturing|Metal Products|Chemical|Printing|Mould|Closures|Composite Materials|Machinery|Glass|Logistics".split(
    "|"
)
CITIES_PIN = "Suzhou Wuxi Ningbo Dongguan Foshan Chengdu Wuhan Qingdao Tianjin Xiamen Kunshan Changzhou".split()


def han_company(form: bool, surname: bool = False) -> str:
    head = (
        (rng.choice(SURNAMES) + rng.choice(("氏", "记", "家")))
        if surname
        else rng.choice(CITIES) + rng.choice(HAN_ADJ)
    )
    base = head + rng.choice(HAN_INDUSTRY)
    return base + (rng.choice(HAN_FORM) if form else "")


def latin_company(form: bool, surname: bool = False) -> str:
    if surname:
        head = rng.choice(
            (
                f"{rng.choice(PIN_SUR)}'s",
                f"{rng.choice(PIN_SUR)} {rng.choice(PIN_GIVEN)}",
                f"{rng.choice(HK_SUR)} {rng.choice(HK_GIVEN)}",
            )
        )
        base = f"{head} {rng.choice(PIN_INDUSTRY)}"
    else:
        base = f"{rng.choice(CITIES_PIN)} {rng.choice(PIN_ADJ)} {rng.choice(PIN_INDUSTRY)}"
    return base + (f" {rng.choice(LATIN_FORM)}" if form else "")


HAN_PLACE_SUFFIX = ["区", "新区", "开发区", "工业园区", "高新区", "镇", "街道", "路", "大道", "村"]


def han_place() -> str:
    kind = rng.choice(("city", "district", "park", "street"))
    if kind == "city":
        return rng.choice(CITIES)
    stem = rng.choice(HAN_ADJ)[:2]
    if kind == "district":
        return rng.choice(CITIES) + stem + rng.choice(("区", "新区", "镇"))
    if kind == "park":
        return rng.choice(CITIES) + stem + rng.choice(("工业园区", "开发区", "高新区", "科技园"))
    return (
        rng.choice(
            ("人民", "中山", "建设", "解放", "和平", rng.choice(SURNAMES) + rng.choice("家庄"))
        )
        + rng.choice(("路", "大道", "东路", "西路"))
        + str(rng.randint(1, 299))
        + "号"
    )


def pin_place() -> str:
    kind = rng.choice(("name_like", "name_like", "district", "park", "street", "city"))
    if kind == "city":
        return rng.choice(CITIES_PIN)
    if kind == "name_like":
        return (
            " ".join(rng.choice(PIN_GIVEN + PIN_SUR) for _ in range(rng.choice((2, 2, 3))))
            + " "
            + rng.choice(("Shan", "Hu", "Jiang", "Zhen", "Cun", "Gang"))
        )
    if kind == "district":
        return f"{rng.choice(PIN_ADJ).split()[0]} {rng.choice(('District', 'New Area', 'Town'))}"
    if kind == "park":
        return f"{rng.choice(CITIES_PIN)} {rng.choice(('Industrial Park', 'High-Tech Zone', 'Economic Development Zone'))}"
    return f"{rng.choice(PIN_SUR)} {rng.choice(PIN_GIVEN)} Road {rng.randint(1, 299)}"


PRODUCT_STEMS = (
    "Zi Jin|Wei Ming|Hua Lan|Jin Hua|Tian Yu|Long Wei|Rui Xin|Bo Han|Xiao Yan|Li Shan".split("|")
)
PRODUCT_NOUNS = ["Cap", "Seal", "Liner", "Closure", "Film", "Tray", "Bottle", "Lid", "Pack"]


def product() -> str:
    kind = rng.choice(("latin", "latin", "han", "model"))
    if kind == "han":
        return (
            rng.choice(HAN_ADJ)
            + rng.choice(("盖", "封口膜", "托盘", "瓶", "内衬", "包装袋"))
            + rng.choice(("", "Pro", "-28", "二号"))
        )
    stem = rng.choice(PRODUCT_STEMS)
    if kind == "model":
        return f"{stem} {rng.choice(PRODUCT_NOUNS)} {rng.choice(('28/410', '38/400', 'X2', 'S300', 'Plus'))}"
    return rng.choice(
        (
            f"{stem} {rng.choice(PRODUCT_NOUNS)}",
            f"{rng.choice(PIN_SUR)} {rng.choice(PRODUCT_NOUNS)} {rng.choice(('Pro', 'Max', 'Lite', 'One'))}",
            f"{rng.choice(PIN_SUR)}{rng.choice(PIN_GIVEN).lower()} {rng.choice(PRODUCT_NOUNS)}",
        )
    )


def np_frame(ctx: str, items: list[str]) -> str:
    """Frame with `{0}`... for the items."""
    n = len(items)
    han = any("一" <= ch <= "鿿" for ch in "".join(items))
    if ctx == "alone":
        return rng.choice(
            [
                "{0}",
                "产品目录第三版\n{0}\n销售部"
                if han
                else "Catalogue, third edition\n{0}\nSales Office",
            ]
        )
    if ctx == "sentence":
        if han:
            return rng.choice(
                [
                    "我们的供应商{0}位于" + city() + "，已通过审核。",
                    "报价单由{0}提供，有效期三十天。",
                    "该订单将由{0}在下周发货。",
                ]
            )
        return rng.choice(
            [
                "Our supplier {0} passed the audit last year.",
                "The quotation was issued by {0} and is valid for thirty days.",
                "The order will be shipped by {0} next week.",
            ]
        )
    if ctx == "list":
        lines = "\n".join("- {%d}" % i for i in range(n))
        return (
            rng.choice(["供应商名单：\n" + lines, lines])
            if han
            else rng.choice(["Suppliers:\n" + lines, lines])
        )
    if ctx == "table":
        return (
            "| 编号 | 名称 | 状态 |\n| 4812 | {0} | 已审核 |"
            if han
            else "| No. | Supplier | Status |\n| 4812 | {0} | Audited |"
        )
    if ctx == "page":
        return rng.choice(
            [
                "关于我们 | About us\n{0} serves customers worldwide. 欢迎咨询。",
                "公司简介\nOur partner: {0}\n总部设在" + city(),
            ]
        )
    raise ValueError(ctx)


NP_CONTEXTS = ["alone", "sentence", "list", "table", "page"]


def build_np(kind: str, make, count: int, *, suzhou: bool = False) -> list[dict]:  # type: ignore[no-untyped-def,type-arg]
    out: list[dict] = []  # type: ignore[type-arg]
    order = [NP_CONTEXTS[i % len(NP_CONTEXTS)] for i in range(count)]
    rng.shuffle(order)
    for ctx in order:
        size = rng.choice((2, 3)) if ctx == "list" else 1
        values = [unique(make) for _ in range(size)]
        text = np_frame(ctx, values)
        spans: list[list[int]] = []
        rest, out_text = text, ""
        for index, value in enumerate(values):
            marker = "{%d}" % index
            position = rest.index(marker)
            out_text += rest[:position]
            spans.append([len(out_text), len(out_text) + len(value)])
            out_text += value
            rest = rest[position + len(marker) :]
        out_text += rest
        out.append(
            {
                "lang": "zh",
                "kind": kind,
                "ctx": ctx,
                "text": out_text,
                "items": spans,
                "suzhou": suzhou,
            }
        )
    return out


SUZHOU = "Suzhou Zi Jin Plastic Co., Ltd"
SUZHOU_CASES = [
    ("alone", "{0}"),
    ("alone", "{0}\nSales Office"),
    ("sentence", "Our supplier {0} passed the audit last year."),
    ("sentence", "The quotation was issued by {0} and is valid for thirty days."),
    ("sentence", "The order will be shipped by {0} next week."),
    (
        "list",
        "Suppliers:\n- Wuxi Hong Da Packaging Co., Ltd\n- {0}\n- Ningbo Rui Feng Closures Ltd",
    ),
    ("list", "Approved suppliers\n- {0}\n- Dongguan Jia He Mould Co., Ltd"),
    (
        "quote",
        '"Last year {0} delivered 40 million closures to our plants," the annual report states.',
    ),
    ("quote", 'From the collected page: "We have worked with {0} since 2015."'),
    ("table", "| No. | Supplier | Status |\n| 4812 | {0} | Audited |"),
    ("page", "关于我们 | About us\n{0} serves customers worldwide. 欢迎咨询。"),
    ("owner_sentence", "BERICAP China and {0} wrote a success story without compare"),
]


def make_suzhou() -> list[dict]:  # type: ignore[type-arg]
    out = []
    for ctx, template in SUZHOU_CASES:
        position = template.index("{0}")
        start = position
        text = template.replace("{0}", SUZHOU)
        items = [[start, start + len(SUZHOU)]]
        if ctx == "owner_sentence":
            items.insert(0, [0, len("BERICAP China")])
        out.append(
            {
                "lang": "zh",
                "kind": "suzhou",
                "ctx": ctx,
                "text": text,
                "items": items,
                "suzhou": True,
            }
        )
    return out


def make_nonperson() -> list[dict]:  # type: ignore[type-arg]
    items: list[dict] = []  # type: ignore[type-arg]
    items += build_np("company_han", lambda: han_company(rng.random() < 0.6), 30)
    items += build_np("company_latin", lambda: latin_company(rng.random() < 0.6), 40)
    items += build_np("company_surname", lambda: han_company(rng.random() < 0.6, True), 16)
    items += build_np("company_surname", lambda: latin_company(rng.random() < 0.6, True), 24)
    items += build_np("place_han", han_place, 22)
    items += build_np("place_pinyin", pin_place, 30)
    items += build_np("product", product, 44)
    items += make_suzhou()
    return items


def write(name: str, items: list[dict]) -> None:  # type: ignore[type-arg]
    rng.shuffle(items)
    with (OUT / name).open("w", encoding="utf-8") as handle:
        for index, item in enumerate(items):
            handle.write(json.dumps({"id": index, **item}, ensure_ascii=False) + "\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    names = make_names()
    nonperson = make_nonperson()
    write("names.jsonl", names)
    write("nonperson.jsonl", nonperson)
    report = sum(len(i["spans"]) for i in names)
    print(len(names), "name items,", report, "names;", len(nonperson), "non-person texts")


if __name__ == "__main__":
    main()
