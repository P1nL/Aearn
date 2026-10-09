"""API-private authored fixtures; not published or source-authorized inventory.

Facts describe option claims, not executions. Keep this module out of public DTOs.
"""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class OptionSpec:
    option_id: Literal["a", "b", "c", "d"]
    label: str
    rhs: tuple[int, ...]
    saved: tuple[int, ...]
    observation: tuple[int, ...]
    reason: str
    failure_reason: str


@dataclass(frozen=True, slots=True)
class QuestionSpec:
    title: str
    prompt: str
    options: tuple[OptionSpec, ...]
    explanation: str


TRACE = QuestionSpec(
    title="追踪保存值与再次重绑定",
    prompt=(
        "按Python顺序赋值规则，选择数值与原因都正确的一项。检查第2/4行的右值，"
        "以及第3/5行重绑定后先前保存的值。\n"
        "~~~python\nsource = 4\nsaved = source\nsource = 9\n"
        "tail = saved + 3\nsaved = 6\nprint(source, saved, tail)\n~~~"
    ),
    options=(
        OptionSpec("a", "第2/4行右值4/7；但source变化使saved联动为9、tail最终为12；输出9 6 12。",
                   (4, 7), (9, 12), (9, 6, 12), "linked_names", "重绑定source不会联动修改saved或tail。"),
        OptionSpec("b", "第2/4行右值提前取后来source的9，得到9/12；saved曾为9、tail为12；输出9 6 12。",
                   (9, 12), (9, 12), (9, 6, 12), "future_rhs", "右值不读取未来的source绑定。"),
        OptionSpec("c", "第2/4行右值4/7；source变9后saved仍4，saved变6后tail仍7；"
                   "输出9 6 7，因为赋值保存当时求出的值。",
                   (4, 7), (4, 7), (9, 6, 7), "snapshot", ""),
        OptionSpec("d", "第2/4行右值4/7，先前saved为4、tail为7，输出9 6 7；"
                   "原因是saved=source建立永久等式，后来两边始终联动。",
                   (4, 7), (4, 7), (9, 6, 7), "permanent_equation", "数值正确，但永久等式解释与重绑定语义矛盾。"),
    ),
    explanation="第2行保存4；第4行用saved=4计算7。后续重绑定只改变目标名字，因此输出9 6 7。",
)


def diagnose_spec(*, guided: bool) -> QuestionSpec:
    # A different explicit instance, not an alias to the practice question.
    price, qty, changed = (5, 4, 7) if guided else (6, 3, 8)
    total, wrong = price * qty, changed * qty
    guidance = (
        "\n先填空表再定位首个偏差：\n|时刻|price|total|receipt|\n|---|---|---|---|\n"
        "|第3行后|?|?|未定义|\n|第4行后|?|?|未定义|\n|第5行后|?|?|?|\n"
        "逐次检查赋值的目标名字和当时右值，不要跳过中间行。"
    ) if guided else ""
    return QuestionSpec(
        title="逐步定位派生值解释偏差" if guided else "诊断首个错误解释",
        prompt=(
            "选择首个错误解释的位置、实际值和原因全部正确的一项。\n"
            f"~~~python\nprice = {price}\nqty = {qty}\ntotal = price * qty\n"
            f"price = {changed}\nreceipt = total + 1\nprint(total, receipt)\n~~~\n"
            f"待诊断解释：①第3行后total={total}；②第4行后total自动变成{wrong}；"
            f"③第5行后receipt={wrong + 1}。" + guidance
        ),
        options=(
            OptionSpec("a", f"首错①：第3/5行右值提前取未来价格，得到{wrong}/{wrong + 1}；"
                       f"total保持{wrong}，输出{wrong} {wrong + 1}。",
                       (wrong, wrong + 1), (wrong,), (1, wrong, wrong + 1), "future_rhs",
                       "第3行只使用当前price，不能提前取未来价格。"),
            OptionSpec("b", f"首错②：第3/5行右值{total}/{total + 1}；第4行后total仍为{total}；"
                       f"输出{total} {total + 1}，因为派生值不自动重算。",
                       (total, total + 1), (total,), (2, total, total + 1), "derived_snapshot", ""),
            OptionSpec("c", f"没有错误：第3行右值{total}，第5行右值{wrong + 1}；"
                       f"total联动为{wrong}，输出{wrong} {wrong + 1}，赋值保存动态公式。",
                       (total, wrong + 1), (wrong,), (0, wrong, wrong + 1), "dynamic_formula",
                       "派生整数不是动态公式；第二步已经发生解释偏差。"),
            OptionSpec("d", f"首错③：第3/5行右值{total}/{total + 1}，total仍为{total}，"
                       f"输出{total} {total + 1}；派生值不重算，但第二步解释正确。",
                       (total, total + 1), (total,), (3, total, total + 1), "derived_snapshot",
                       "实际值正确，但首个错误是②而非③。"),
        ),
        explanation=(f"第3行用{price}×{qty}求出{total}；第4行只重绑定price。"
                     f"故②是首错，第5行读取total再加1，输出{total} {total + 1}。"),
    )


REPAIR = QuestionSpec(
    title="同时满足两个输入场景的最小修复",
    prompt=(
        "入口x分别为3和8。每个补丁替换缺失的三行，然后执行print(old, new)。"
        "要求old保存入口x；把x增加2后，new是更新后x的两倍。两场景均须满足，禁止写死"
        "某个场景结果。选择唯一符合全部条件的补丁，核对保存/更新/计算三处右值时点。"
    ),
    options=(
        OptionSpec("a", "~~~python\nx = x + 2\nold = x\nnew = x * 2\n~~~\n先更新再保存。",
                   (5, 5, 10, 10, 10, 20), (5, 10), (5, 10, 10, 20), "save_after_refresh",
                   "old读取更新后的x，两场景都丢失入口值。"),
        OptionSpec("b", "~~~python\nold = x\nx = x + 2\nnew = x * 2\n~~~\n先保存旧值，再更新并计算new。",
                   (3, 5, 10, 8, 10, 20), (3, 8), (3, 10, 8, 20), "save_then_refresh", ""),
        OptionSpec("c", "~~~python\nold = x\nx = x + 2\nnew = 10\n~~~\n保存旧值，用固定10作为new。",
                   (3, 5, 10, 8, 10, 10), (3, 8), (3, 10, 8, 10), "literal_result",
                   "x=3时碰巧正确，但x=8时new应为20而非10；且违反依赖约束。"),
        OptionSpec("d", "~~~python\nold = x\nnew = x * 2\nx = x + 2\n~~~\n先计算new，再更新x。",
                   (3, 5, 6, 8, 10, 16), (3, 8), (3, 6, 8, 16), "derive_before_refresh",
                   "new用的是更新前右值；后续x增加2不会自动重算new。"),
    ),
    explanation="先保存old=x，再x=x+2，最后new=x*2。入口3产生3 10，入口8产生8 20；重绑定不改变old。",
)

COUNTEREXAMPLE = QuestionSpec(
    title="选择真正反驳名字联动说法的反例",
    prompt=(
        "有人断言：对整数执行saved = source后，只要把source重新赋成不同整数，saved也一定"
        "随之改变。选择唯一触发source重绑定、反驳断言且右值说明与输出一致的选项。"
    ),
    options=(
        OptionSpec("a", "~~~python\nsource = 4\nsaved = source\nprint(source, saved)\n~~~\n"
                   "保存时右值4，saved仍4，输出4 4；这足以反驳断言。",
                   (4,), (4,), (4, 4), "no_rebinding", "没有source重绑定，未触发命题前提。"),
        OptionSpec("b", "~~~python\nsource = 4\nsaved = source\nsaved = 9\nprint(source, saved)\n~~~\n"
                   "保存时右值4，saved变9，输出4 9；这足以反驳断言。",
                   (4,), (9,), (4, 9), "wrong_target", "改变saved而非source，不是该命题的反例。"),
        OptionSpec("c", "~~~python\nsource = 4\nsaved = source\nsource = 9\nprint(source, saved)\n~~~\n"
                   "保存时右值4，source重绑定后saved仍4；输出9 4，故不是联动关系。",
                   (4,), (4,), (9, 4), "source_rebound_saved_preserved", ""),
        OptionSpec("d", "~~~python\nsource = 4\nsaved = source\nsource = 9\nprint(source, saved)\n~~~\n"
                   "saved的右值延到print时取9，saved变9；输出9 9，却说明saved保持原值，因而反驳断言。",
                   (9,), (9,), (9, 9), "delayed_rhs", "右值在赋值时求出；声称输出与程序及反驳结论矛盾。"),
    ),
    explanation="反例必须有source重绑定这一前提。保存时右值为4，source变9不改变saved，因此9 4反驳联动断言。",
)
