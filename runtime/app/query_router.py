"""快速、复杂和知识查询路由。"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class QueryRoute:
    kind: str
    model_role: str
    use_rag: bool


MOTION_PREFIXES = (
    "前进", "向前走", "往前走", "直走", "走直线",
    "左转", "向左转", "右转", "向右转",
    "停止", "立即停止", "紧急停止", "停下来",
)

QUESTION_MARKERS = (
    "能不能", "可不可以", "可以吗", "是否",
    "为什么", "怎么", "如何", "吗", "呢",
)

KNOWLEDGE_MARKERS = (
    "知识库", "项目文档", "项目文件", "本地文档",
    "说明书", "手册", "接口文档", "项目代码",
    "源代码", "源码", "配置文件", "数据库",
    "日志", "报错信息", "这个项目", "项目中",
    "代码中", "文件中", "文档中",
)

COMPLEX_MARKERS = (
    "详细分析", "深入分析", "综合分析", "分析一下",
    "比较", "对比", "权衡", "设计方案",
    "实现方案", "完整方案", "系统架构",
    "架构设计", "优化方案", "排查", "诊断",
    "推导", "评估", "总结", "解释原因",
    "为什么", "原理", "如何实现", "优缺点",
)


def normalize(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:；;]+", "", text)


def route_query(text: str) -> QueryRoute:
    value = normalize(text)

    motion = (
        value.startswith(MOTION_PREFIXES)
        and not any(word in value for word in QUESTION_MARKERS)
    )
    if motion:
        return QueryRoute("motion", "fast", False)

    knowledge = any(word in value for word in KNOWLEDGE_MARKERS)
    complex_query = (
        len(value) >= 50
        or any(word in value for word in COMPLEX_MARKERS)
    )

    if knowledge and complex_query:
        return QueryRoute("complex_knowledge", "complex", True)

    if knowledge:
        return QueryRoute("knowledge", "fast", True)

    if complex_query:
        return QueryRoute("complex_chat", "complex", False)

    return QueryRoute("normal_chat", "fast", False)
