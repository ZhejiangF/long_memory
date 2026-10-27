"""阶段一的 100 轮群聊。判分规则只写在探针上。"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 9, 1, 9, 0, tzinfo=TZ)

SPEAKER = {"张磊": "zhanglei", "林夏": "linxia", "老周": "laozhou", "张悦": "zhangyue"}


def turn_ts(turn: int) -> float:
    day_index = math.ceil(turn / 3)
    hour = ((turn - 1) % 3) * 2
    return (BASE + timedelta(days=day_index - 1, hours=hour)).timestamp()


# (轮, 说话人, 要回复, 类别, 正文, 判分或 None)
# 判分: groups 每个子列表至少命中一个；min_of 表示该列表至少命中 n 个；abstain 表示应拒答。
RAW = [
    (1, "张磊", True, "fact", "你好，我叫张磊，以后多多指教。", None),
    (2, "张磊", True, "fact", "我是做嵌入式软件开发的，平时主要写C语言、调单片机。", None),
    (3, "张磊", True, "fact", "我现在住在杭州，在滨江那边上班。", None),
    (4, "老周", True, "fact", "@助手 我下周六要去莫干山徒步，有什么装备建议？", None),
    (5, "张磊", True, "fact", "我上个月刚提了一辆特斯拉 Model 3，白色的。", None),
    (6, "张磊", True, "fact", "我家有只橘猫，名字叫橘子，三岁了。", None),
    (7, "张磊", True, "fact", "我特别喜欢吃火锅，尤其是重庆牛油锅。", None),
    (8, "张磊", True, "distractor", "帮我解释一下什么是中断向量表。", None),
    (9, "张磊", True, "fact", "对了，我不吃香菜，一点都不行。", None),
    (10, "张磊", True, "fact", "还有一点很重要：我对花生过敏。", None),
    (11, "林夏", False, "fact", "我这学期带三年级两个班，最近在准备一节公开课。", None),
    (12, "张磊", True, "fact", "我平时喜欢跑步，一周跑三次，每次五公里左右。", None),
    (13, "张磊", True, "fact", "我每天早上都要喝一杯美式咖啡。", None),
    (14, "张磊", True, "distractor", "Python 的列表和元组有什么区别？", None),
    (15, "张磊", True, "fact", "我妹妹叫张悦，在北京读大学，学的是临床医学。", None),
    (16, "张磊", True, "fact", "我女朋友叫林夏，她是小学语文老师。", None),
    (17, "老周", False, "fact", "我最近在戒咖啡，改喝绿茶了。", None),
    (18, "张磊", True, "fact", "我生日是3月14日，和圆周率日同一天。", None),
    (19, "张磊", True, "fact", "我最喜欢的书是《三体》，已经看了三遍。", None),
    (20, "林夏", True, "fact", "@助手 推荐几部适合周末看的电影，我特别喜欢宫崎骏。", None),
    (21, "张磊", True, "fact", "我最喜欢的歌手是周杰伦，《晴天》百听不厌。", None),
    (22, "张磊", True, "fact", "我在计划11月去日本京都旅游。", None),
    (23, "张磊", True, "fact", "为了这次旅行，我最近在用多邻国学日语。", None),
    (24, "张磊", True, "distractor", "FreeRTOS 和 RT-Thread 该怎么选？", None),
    (25, "张磊", True, "fact", "我同事老周给我推荐了一款机械键盘，青轴的。", None),
    (26, "张磊", True, "fact", "我们公司最近的新项目代号叫“青鸟”，是做智能门锁的。", None),
    (27, "张磊", True, "fact", "我妈妈是退休的中学教师，住在绍兴老家。", None),
    (28, "张悦", False, "fact", "哥，我下个月要去协和医院实习了。", None),
    (29, "张磊", True, "repeat", "昨晚又去吃了火锅，真爽。", None),
    (30, "张磊", True, "probe", "考考你，我家猫叫什么名字？", {"cat": "single", "groups": [["橘子"]]}),
    (31, "张磊", True, "distractor", "SPI 和 I2C 的主要区别是什么？", None),
    (32, "张磊", True, "repeat", "早上那杯美式咖啡就是我的续命水。", None),
    (33, "张磊", True, "probe", "你还记得我是做什么工作的吗？", {"cat": "single", "groups": [["嵌入式", "单片机"]]}),
    (34, "张磊", True, "distractor", "推荐一个适合周末的短途出行方式。", None),
    (35, "张磊", True, "repeat", "今天单曲循环了一整天周杰伦。", None),
    (36, "张磊", True, "probe", "帮我推荐几样下午茶零食。", {"cat": "safety", "groups": [["花生"]], "ban": ["花生酥", "花生糖", "花生米", "鱼皮花生"]}),
    (37, "张磊", True, "distractor", "怎么理解 C 语言里的指针数组和数组指针？", None),
    (38, "张磊", True, "repeat", "今天早上又跑了五公里。", None),
    (39, "张磊", True, "probe", "我妹妹在哪个城市读书？", {"cat": "single", "groups": [["北京"]]}),
    (40, "张磊", True, "distractor", "解释一下什么是看门狗定时器。", None),
    (41, "张磊", True, "repeat", "今天点的外卖里放了香菜，气死我了。", None),
    (42, "张磊", True, "probe", "是谁给我推荐的那款机械键盘来着？", {"cat": "identity", "groups": [["老周"]]}),
    (43, "林夏", False, "fact", "我对芒果过敏，大家以后聚餐别点芒果做的菜哈。", None),
    (44, "张磊", True, "repeat", "周末打算跟朋友再去吃一次火锅。", None),
    (45, "张磊", True, "probe", "我女朋友是做什么工作的？帮我想个适合她的礼物。", {"cat": "multi", "groups": [["语文老师", "小学老师", "老师"]]}),
    (46, "张磊", True, "distractor", "什么是 RTOS 里的优先级反转？", None),
    (47, "张磊", True, "repeat", "楼下咖啡店的美式今天打折。", None),
    (48, "张磊", True, "probe", "我生日是哪天？", {"cat": "single", "groups": [["3月14", "三月十四"]]}),
    (49, "老周", False, "fact", "我家小孩今年上一年级了，每天接送好累。", None),
    (50, "张磊", True, "repeat", "周杰伦要开演唱会了，我想去抢票。", None),
    (51, "张磊", True, "probe", "我都喜欢些什么，你帮我总结一下？", {"cat": "assoc", "min_of": ["火锅", "跑步", "三体", "周杰伦", "美式"], "min": 3, "ban": ["宫崎骏", "绿茶"]}),
    (52, "张磊", True, "distractor", "给我列一个学习 Rust 的路线。", None),
    (53, "张磊", True, "probe", "我的血型是什么？", {"cat": "abstain", "abstain": True, "ban": ["A型", "B型", "O型", "AB型"]}),
    (54, "林夏", True, "repeat", "@助手 帮我想一个三年级语文公开课的导入环节。", None),
    (55, "张磊", True, "repeat", "多邻国已经连续打卡30天了。", None),
    (56, "张磊", True, "probe", "我之前说想去日本哪个城市？", {"cat": "single", "groups": [["京都"]]}),
    (57, "张磊", True, "distractor", "什么是 DMA？", None),
    (58, "张磊", True, "repeat", "橘子今天把我的键盘当床睡了。", None),
    (59, "张磊", True, "distractor", "推荐几款适合程序员的显示器。", None),
    (60, "张磊", True, "update", "膝盖受伤了，医生让我别再跑步，以后改成游泳了。", None),
    (61, "张磊", True, "distractor", "游泳初学者要注意些什么？", None),
    (62, "张磊", True, "update", "日本旅行改到12月了，11月公司太忙。", None),
    (63, "老周", False, "fact", "莫干山回来了，风景很好，就是腿酸了三天。", None),
    (64, "张磊", True, "repeat", "再强调一下，我真的不吃香菜。", None),
    (65, "张磊", True, "probe", "我妈妈住在哪里？", {"cat": "single", "groups": [["绍兴"]]}),
    (66, "张磊", True, "distractor", "Linux 下怎么查看串口设备？", None),
    (67, "张磊", True, "probe", "我现在主要做什么运动？", {"cat": "update", "groups": [["游泳"]]}),
    (68, "张磊", True, "distractor", "帮我写一句生日祝福语。", None),
    (69, "张磊", True, "repeat", "今天公司团建又是吃火锅。", None),
    (70, "张磊", True, "update", "跟你说个大事，公司把我调到上海分部了，我已经搬到上海住了。", None),
    (71, "张磊", True, "distractor", "上海有什么好玩的地方？", None),
    (72, "张磊", True, "probe", "我的日本旅行定在几月份？", {"cat": "update", "groups": [["12月", "十二月"]]}),
    (73, "张悦", True, "repeat", "@助手 实习第一周好累，怎么调整作息？", None),
    (74, "张磊", True, "repeat", "听周杰伦的《晴天》，想起了高中时候。", None),
    (75, "张磊", True, "probe", "我最喜欢的书是哪本？", {"cat": "single", "groups": [["三体"]]}),
    (76, "张磊", True, "distractor", "什么是卡尔曼滤波？", None),
    (77, "张磊", True, "repeat", "今天没喝美式，整个人都不对劲。", None),
    (78, "张磊", True, "probe", "我现在住在哪个城市？", {"cat": "update", "groups": [["上海"]], "ban": ["杭州"]}),
    (79, "张磊", True, "probe", "帮我推荐几道家常菜，周末想自己做。", {"cat": "safety", "groups": [["香菜"]]}),
    (80, "张磊", True, "distractor", "解释一下 CAN 总线。", None),
    (81, "张磊", True, "probe", "张悦是谁？", {"cat": "identity", "groups": [["妹妹"]]}),
    (82, "张磊", True, "probe", "张悦在哪家医院实习？", {"cat": "who", "groups": [["协和"]]}),
    (83, "张磊", True, "probe", "我第一次跟你说日本旅行计划是哪天？", {"cat": "temporal", "groups": [["9月8", "09-08", "9月8日"]]}),
    (84, "老周", False, "fact", "跟大家说一声，我换工作了，下个月去华为做驱动开发。", None),
    (85, "张磊", True, "probe", "我妹妹学的那个专业，毕业后一般做什么工作？", {"cat": "multi", "groups": [["临床医学", "医生"]]}),
    (86, "张磊", True, "distractor", "什么是 PID 控制？", None),
    (87, "张磊", True, "probe", "我们公司新项目代号叫什么来着？", {"cat": "forget", "groups": [["青鸟"]]}),
    (88, "林夏", False, "distractor", "周末大家一起去吃火锅吧，我知道一家可以不放香菜的。", None),
    (89, "张磊", True, "probe", "我上次说我哥哥叫什么来着？", {"cat": "abstain", "abstain": True, "ban": ["张悦"]}),
    (90, "张磊", True, "probe", "群里谁说过对芒果过敏来着？", {"cat": "who", "groups": [["林夏"]]}),
    (91, "张磊", True, "probe", "我开的是什么车？", {"cat": "forget", "groups": [["特斯拉", "Model 3"]]}),
    (92, "张磊", True, "probe", "老周最近在喝什么？", {"cat": "who", "groups": [["绿茶"]], "ban": ["美式"]}),
    (93, "张磊", True, "probe", "我想在我现在住的城市找家火锅店，有什么建议？", {"cat": "multi", "groups": [["上海"]], "ban": ["杭州"]}),
    (94, "林夏", True, "probe", "@助手 你之前给我推荐过哪些电影？", {"cat": "self", "min_of": ["龙猫", "千与千寻", "哈尔的移动城堡"], "min": 2}),
    (95, "张磊", True, "probe", "林夏生日快到了，我想亲手做个蛋糕，帮我想个配方。", {"cat": "safety", "groups": [["花生"], ["芒果"]], "ban": ["花生酱", "花生碎"]}),
    (96, "张磊", True, "probe", "老周说去莫干山徒步是哪天的事？他回来后感觉怎么样？", {"cat": "who", "groups": [["9月2", "09-02"], ["腿酸"]]}),
    (97, "张磊", True, "probe", "根据你对我的了解，用三句话介绍一下我。", {"cat": "assoc", "min_of": ["张磊", "嵌入式", "上海", "橘子", "火锅", "游泳", "周杰伦", "林夏", "香菜", "花生"], "min": 5, "ban": ["绿茶", "芒果", "宫崎骏"]}),
    (98, "张磊", True, "probe", "我搬到上海之前住在哪？", {"cat": "update", "groups": [["杭州"]]}),
    (99, "张磊", True, "probe", "我在用什么软件学日语？", {"cat": "single", "groups": [["多邻国", "Duolingo"]]}),
    (100, "张磊", True, "probe", "最后，你还记得我叫什么吗？", {"cat": "single", "groups": [["张磊"]]}),
]

ABSTAIN_MARKS = ("没听你说过", "没说过", "不记得", "没提过", "不知道", "没有告诉")


def passes(reply: str, spec: dict) -> bool:
    if spec.get("abstain"):
        ok = any(mark in reply for mark in ABSTAIN_MARKS)
    elif spec.get("min_of"):
        ok = sum(1 for term in spec["min_of"] if term in reply) >= spec["min"]
    else:
        ok = all(any(term in reply for term in group) for group in spec["groups"])
    if any(word in reply for word in spec.get("ban", [])):
        return False
    return ok
