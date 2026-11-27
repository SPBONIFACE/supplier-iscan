"""Chinese names (#100): the rules around the models, without the model (fake detector).

The figures of the real model are in `test_chinese_model.py` and `measure_detector --zh`.
"""

import pytest

from app.redaction import OMISSION, RedactionUnavailable, Redactor
from app.redaction.detector import chunk_text
from tests.redaction.support import FakeDetector, fake_redactor


def redact(text: str, *found: str) -> str:
    return fake_redactor(*found).redact(text).text


@pytest.mark.parametrize(
    ("text", "gone", "kept"),
    [
        ("联系人：王浩然\n地点：上海", ("王浩然",), ("联系人：", "上海")),
        ("联系人：\n陈雨桐\n地点：宁波", ("陈雨桐",), ("联系人", "宁波")),
        ("Contact: 黃文秋\nLocation: Wuhan", ("黃文秋",), ("Contact", "Wuhan")),
        ("此致\n敬礼\n段琪冬\n财务部", ("段琪冬",), ("敬礼", "财务部")),
        ("欧阳雅强", ("欧阳雅强",), ()),
        ("产品目录第三版\n贺国\n佛山", ("贺国",), ("产品目录", "佛山")),
        ("| 4812 | 王浩然 | 已发货 | 5月12日 |", ("王浩然",), ("已发货", "5月12日")),
        ("团队：\n- 王浩然\n- 司马光远\n- 谭春", ("王浩然", "司马光远", "谭春"), ("团队",)),
        ("昨天李明与我们的仓库确认了交货日期。", ("李明",), ("昨天", "仓库")),
        ("审计报告在季度末前由陈雨桐签字批准。", ("陈雨桐",), ("审计报告", "批准")),
        ("我们的代表姜敏将在周三回复您的询价。", ("姜敏",), ("代表", "回复")),
        ("上个月，蔡倩参观了我们的工厂。", ("蔡倩",), ("上个月", "工厂")),
        ("阿依古丽·买买提", ("阿依古丽", "买买提"), ()),
        ("联系人：艾尔肯·阿不都热依木，销售部", ("艾尔肯", "阿不都热依木"), ("销售部",)),
    ],
)
def test_han_names_are_hidden_by_rule(
    text: str, gone: tuple[str, ...], kept: tuple[str, ...]
) -> None:
    out = redact(text)

    assert OMISSION in out
    for item in gone:
        assert item not in out, (item, out)
    for item in kept:
        assert item in out, (item, out)


@pytest.mark.parametrize(
    ("text", "gone", "title"),
    [
        ("张经理将在周三回复。", "张", "经理"),
        ("请联系王总。", "王", "总"),
        ("李先生已确认订单。", "李", "先生"),
        ("联系人皇甫凤女士，欢迎来电。", "皇甫凤", "女士"),
        ("总经理王浩然表示同意。", "王浩然", "总经理"),
        ("产品咨询请联系 经理夏侯诗 (Sales)", "夏侯诗", "经理"),
        ("孟军静老师", "孟军静", "老师"),
        ("- 邵经理\n- 杨博士", "邵", "经理"),
    ],
)
def test_a_han_title_next_to_a_name_stays(text: str, gone: str, title: str) -> None:
    out = redact(text)

    assert gone not in out and title in out and OMISSION in out


def test_a_title_inside_a_model_span_is_cut_out() -> None:
    text = "产品咨询请联系 陶老师 (Sales)"

    out = redact(text, "陶老师 (Sales)")

    assert "老师" in out and "陶" not in out


def test_a_han_name_split_by_a_line_break_is_hidden_whole() -> None:
    out = redact("三月份该档案由王\n浩然在发货前处理。")

    assert "王" not in out and "浩然" not in out and "处理" in out


@pytest.mark.parametrize(
    "text",
    [
        "苏州紫金塑料有限公司",
        "我们的供应商苏州紫金塑料有限公司位于苏州，已通过审核。",
        "供应商名单：\n- 苏州泰和模具\n- 天津紫金化工\n- 上海华兴物流",
        "付记印刷集团有限公司",
        "李氏塑业有限公司",
        "苏州",
        "武汉\n金华\n石家庄",
        "苏州工业园区",
        "人民路88号",
        "高度重视质量，高级经理已确认。",
        "我们的价值观：诚信、安全和可持续发展。",
        "产品系列：明珠瓶和紫金盖。",
    ],
)
def test_companies_places_and_common_words_in_han_stay(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("李氏塑业有限公司", "李氏塑业"),
        ("苏州泰和模具", "苏州泰"),
        ("明珠瓶", "明珠瓶"),
        ("上海紫金路", "紫金"),
    ],
)
def test_a_model_span_inside_a_han_company_is_dropped(text: str, found: str) -> None:
    assert redact(text, found) == text


@pytest.mark.parametrize(
    ("text", "gone", "kept"),
    [
        ("Contact: Zhang Wei\nLocation: Leeds", ("Zhang", "Wei"), ("Contact",)),
        ("Contact: Wei Zhang", ("Zhang", "Wei"), ("Contact",)),
        ("Sales: ZHANG Wei, Purchasing", ("ZHANG", "Wei"), ("Purchasing",)),
        ("Signed by CHAN TAI MAN yesterday", ("CHAN", "TAI", "MAN"), ("Signed by",)),
        ("The file went to Chan Tai Man in Kowloon.", ("Chan", "Tai", "Man"), ("Kowloon",)),
        ("| 4812 | Lin Yu-ting | Shipped | 12 May |", ("Lin", "Yu-ting"), ("Shipped",)),
        (
            "Welcome to the supplier portal\nXiahua Hu\nSuzhou",
            ("Xiahua", "Hu"),
            ("portal", "Suzhou"),
        ),
        ("Our contact is Dr. Wei Zhang from the plant.", ("Wei", "Zhang"), ("Dr.",)),
        ("Mr. Zhang Wei will call.", ("Zhang", "Wei"), ("Mr.",)),
        ("Manager Li will call back.", ("Li",), ("Manager", "will call")),
        (
            "Participants\n- Director Deng\n- Manager Xiong",
            ("Deng", "Xiong"),
            ("Director", "Manager"),
        ),
        ("zhang wei", ("zhang", "wei"), ()),
        ("Team:\n- Minghong Fang\n- Hao Song", ("Minghong", "Fang", "Hao", "Song"), ("Team",)),
    ],
)
def test_romanised_chinese_names_are_hidden_by_rule(
    text: str, gone: tuple[str, ...], kept: tuple[str, ...]
) -> None:
    out = redact(text)

    assert OMISSION in out
    for item in gone:
        assert item not in out, (item, out)
    for item in kept:
        assert item in out, (item, out)


@pytest.mark.parametrize(
    "text",
    [
        "Suzhou Zi Jin Plastic Co., Ltd",
        "Our supplier Suzhou Zi Jin Plastic Co., Ltd passed the audit last year.",
        "Suppliers:\n- Wuxi Hong Da Packaging Co., Ltd\n- Suzhou Zi Jin Plastic Co., Ltd",
        '"We have worked with Suzhou Zi Jin Plastic Co., Ltd since 2015."',
        "BERICAP China and Suzhou Zi Jin Plastic Co., Ltd wrote a success story without compare",
        "Suzhou Zi Jin Plastic",
        "Wang Seal 28/410",
        "Hong Kong",
        "Zi Jin Shan",
        "Changzhou Wang Hua Container Co. Ltd",
        "Lin Tai Precision Industrial Co., Ltd",
        "Zhang Jiang High-Tech Park",
        "Kind regards,\nSales Office\nLeeds",
    ],
)
def test_chinese_company_place_and_product_names_stay(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Wei Cap Lite", "Wei Cap Lite"),
        ("Li Shan Seal S300", "Li Shan Seal"),
        ("Wei's Printing", "Wei's"),
        ("Dong Hong Road 162", "Dong Hong Road 162"),
    ],
)
def test_a_model_span_that_is_a_chinese_product_or_address_is_dropped(
    text: str, found: str
) -> None:
    assert redact(text, found) == text


def test_a_model_span_with_a_role_word_keeps_the_role() -> None:
    out = redact("- Manager Peng", "Manager Peng")

    assert "Manager" in out and "Peng" not in out


def test_a_foreign_name_with_a_product_word_is_still_hidden() -> None:
    assert "Glass" not in redact("Contact: Philip Glass", "Philip Glass")
    assert "Park" not in redact("Contact: Jin Park", "Jin Park")


def test_the_same_name_in_han_and_romanised_form_goes_twice() -> None:
    # the Han half is the model's (nothing around it says "person"); the rules take the other
    out = redact("王浩然 (Wang Haoran) is our contact for the Suzhou plant.", "王浩然")

    assert "王浩然" not in out and "Wang" not in out and "Haoran" not in out
    assert "Suzhou plant" in out


def test_han_mixed_with_latin_in_one_line() -> None:
    out = redact("Contact: Chan Tai Man 联系人：陈大文 Sales")

    assert "Chan" not in out and "陈大文" not in out and "Sales" in out


def test_full_width_blanks_and_punctuation_around_a_name() -> None:
    out = redact("联系人：　王浩然　电话见网站。")

    assert "王浩然" not in out and "联系人" in out and "电话" in out


@pytest.mark.parametrize("text", ["", "1234 !!! ???", "—— ·· 、、", "\n\n", "   "])
def test_texts_without_letters_are_returned_as_they_are(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize("name_start", [0, 1, 394, 396, 397, 398, 399, 400, 460, 497, 498])
def test_a_han_name_lies_whole_in_one_chunk_at_every_cut(name_start: int) -> None:
    filler = "我们的产品系列包括各种塑料瓶盖和包装材料。"
    text = (filler * 60)[:700]
    name = "王浩然"
    text = text[:name_start] + name + text[name_start + len(name) :]

    chunks = chunk_text(text, 400, 100)

    assert any(
        offset <= name_start and name_start + len(name) <= offset + len(piece)
        for offset, piece in chunks
    )


def test_a_name_at_the_very_start_and_end_of_a_long_han_text_is_hidden() -> None:
    body = "我们的产品系列包括各种塑料瓶盖和包装材料。" * 30
    out = redact("联系人：王浩然\n" + body + "\n签名：\n陈雨桐")

    assert "王浩然" not in out and "陈雨桐" not in out and body in out


def test_a_failing_han_detector_still_fails_closed() -> None:
    class Failing:
        def person_spans(self, texts: object) -> list[list[tuple[int, int]]]:
            raise RuntimeError("boom")

    redactor = Redactor(FakeDetector(), Failing())

    with pytest.raises(RedactionUnavailable):
        redactor.redact("联系人：王浩然")


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        ("Contact: Anna Seal", "Seal"),
        ("Regards,\nTom Mold", "Mold"),
        ("Contact: Jane Liner", "Liner"),
        ("Contact: Mark Tray", "Tray"),
        ("Contact: Peter Plastic Smith", "Smith"),
    ],
)
def test_a_name_with_a_product_word_is_still_hidden_by_the_rules(text: str, gone: str) -> None:
    out = redact(text)

    assert OMISSION in out and gone not in out


def test_a_chinese_product_before_a_job_line_stays() -> None:
    text = "Catalogue, third edition\nLi Shan Seal\nSales Office"

    assert redact(text) == text


@pytest.mark.parametrize("name", ["Anna Seal", "Tom Mold", "Jane Liner"])
def test_a_model_span_with_a_product_word_but_no_chinese_surname_is_hidden(name: str) -> None:
    text = f"Contact: {name} will call back."

    out = redact(text, name)

    assert name.split()[1] not in out and OMISSION in out


def test_a_model_span_with_a_chinese_surname_and_a_product_word_is_kept() -> None:
    text = "Our product Li Shan Seal is shipped."

    assert redact(text, "Li Shan Seal") == text
