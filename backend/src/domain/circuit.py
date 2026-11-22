"""接线、开关与夜巡观测的断点诊断。

把线路建成无向图：开关闭合且未断的线路导电，灯组节点与任一电源节点
连通即为亮（灯组只要还有一路来电就算亮）。诊断是在候选线路中找最少
断点，使逐灯模拟的亮灭与夜巡观测全部一致。求解按断点数递增枚举，
可中断续算；全部候选搜完仍无解时，再找至少舍弃哪些观测才能算通。
"""

import time
from collections import deque
from itertools import combinations
from math import comb

SOURCE, SEGMENT, SWITCH, LAMP, OBSERVATION = "电源点", "线路", "开关", "灯组", "观测"
CLOSED, OPEN = "闭合", "断开"
LIT, DARK = "亮", "灭"
RECORD_TYPES = [SOURCE, SEGMENT, SWITCH, LAMP, OBSERVATION]

CIRCUIT_FIELDS = [
    {"key": "record_type", "label": "记录类型", "type": "select", "required": True, "options": RECORD_TYPES},
    {"key": "source_id", "label": "电源编号", "type": "string", "required": False},
    {"key": "segment_id", "label": "线路编号", "type": "string", "required": False},
    {"key": "switch_id", "label": "开关编号", "type": "string", "required": False},
    {"key": "site_id", "label": "灯组编号", "type": "string", "required": False},
    {"key": "node_a", "label": "节点甲", "type": "string", "required": False},
    {"key": "node_b", "label": "节点乙", "type": "string", "required": False},
    {"key": "switch_state", "label": "开关状态", "type": "select", "required": False, "options": [CLOSED, OPEN]},
    {"key": "observed", "label": "夜巡观测", "type": "select", "required": False, "options": [LIT, DARK]},
]

CIRCUIT_PARAMS = [
    {"key": "max_breaks", "label": "断点搜索上限（处）", "type": "int", "required": True,
     "min": 1, "max": 40, "default": 12,
     "help": "按断点数从小到大搜索。候选线路不足上限时搜到穷尽，可证明无解。"},
    {"key": "pass_seconds", "label": "单轮求解秒数", "type": "int", "required": True,
     "min": 5, "max": 110, "default": 50,
     "help": "超时自动保存进度并排队续算，已排除的断点组合不会重查。"},
]

DISPLAY_SOLUTIONS = 50
DISPLAY_DISCARDS = 20


class _Deadline(Exception):
    """单轮求解时限已到，由调用方保存进度。"""


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空，请填写文本。")
    return value.strip()


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def validate_rows(rows):
    """校验接线、开关、灯组与观测记录，返回规范化的独立记录。"""
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError("接线与观测明细为空，请导入记录。")

    sources, segments, switches, lamps, observations = {}, {}, {}, {}, {}
    records = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 条记录格式有误。")
        kind = row.get("record_type")
        record = {"record_type": kind}
        if kind == SOURCE:
            source_id = _text(row.get("source_id"), f"第 {index} 条记录的电源编号").upper()
            if source_id in sources:
                raise ValueError(f"电源编号「{source_id}」重复。")
            if any(not _blank(row.get(key)) for key in
                   ("segment_id", "switch_id", "site_id", "node_b", "switch_state", "observed")):
                raise ValueError(f"电源「{source_id}」的电源行只填电源编号和节点甲。")
            record.update(source_id=source_id,
                          node=_text(row.get("node_a"), f"电源「{source_id}」的节点甲").upper())
            sources[source_id] = record
        elif kind == SEGMENT:
            segment_id = _text(row.get("segment_id"), f"第 {index} 条记录的线路编号").upper()
            if segment_id in segments:
                raise ValueError(f"线路编号「{segment_id}」重复。")
            if any(not _blank(row.get(key)) for key in
                   ("source_id", "switch_id", "site_id", "switch_state", "observed")):
                raise ValueError(f"线路「{segment_id}」的线路行只填线路编号和两个节点。")
            node_a = _text(row.get("node_a"), f"线路「{segment_id}」的节点甲").upper()
            node_b = _text(row.get("node_b"), f"线路「{segment_id}」的节点乙").upper()
            if node_a == node_b:
                raise ValueError(f"线路「{segment_id}」的两个节点不能相同。")
            record.update(segment_id=segment_id, node_a=node_a, node_b=node_b)
            segments[segment_id] = record
        elif kind == SWITCH:
            switch_id = _text(row.get("switch_id"), f"第 {index} 条记录的开关编号").upper()
            if switch_id in switches:
                raise ValueError(f"开关编号「{switch_id}」重复。")
            if any(not _blank(row.get(key)) for key in
                   ("source_id", "site_id", "node_a", "node_b", "observed")):
                raise ValueError(f"开关「{switch_id}」的开关行只填开关编号、所属线路和开关状态。")
            segment_id = _text(row.get("segment_id"), f"开关「{switch_id}」的所属线路").upper()
            state = row.get("switch_state")
            if state not in (CLOSED, OPEN):
                raise ValueError(f"开关「{switch_id}」的开关状态须为「{CLOSED}」或「{OPEN}」。")
            record.update(switch_id=switch_id, segment_id=segment_id, switch_state=state)
            switches[switch_id] = record
        elif kind == LAMP:
            site_id = _text(row.get("site_id"), f"第 {index} 条记录的灯组编号").upper()
            if site_id in lamps:
                raise ValueError(f"灯组编号「{site_id}」重复。")
            if any(not _blank(row.get(key)) for key in
                   ("source_id", "segment_id", "switch_id", "node_b", "switch_state", "observed")):
                raise ValueError(f"灯组「{site_id}」的灯组行只填灯组编号和节点甲。")
            record.update(site_id=site_id,
                          node=_text(row.get("node_a"), f"灯组「{site_id}」的节点甲").upper())
            lamps[site_id] = record
        elif kind == OBSERVATION:
            site_id = _text(row.get("site_id"), f"第 {index} 条记录的灯组编号").upper()
            if site_id in observations:
                raise ValueError(f"灯组「{site_id}」在同一时段已有观测，请勿重复记录。")
            if any(not _blank(row.get(key)) for key in
                   ("source_id", "segment_id", "switch_id", "node_a", "node_b", "switch_state")):
                raise ValueError(f"灯组「{site_id}」的观测行只填灯组编号和夜巡观测。")
            observed = row.get("observed")
            if observed not in (LIT, DARK):
                raise ValueError(f"灯组「{site_id}」的夜巡观测须为「{LIT}」或「{DARK}」。")
            record.update(site_id=site_id, observed=observed)
            observations[site_id] = record
        else:
            raise ValueError(f"第 {index} 条记录的记录类型须为「{'」「'.join(RECORD_TYPES)}」之一。")
        records.append(record)

    if not sources:
        raise ValueError("缺少电源点记录，请至少登记一个电源。")
    if not segments:
        raise ValueError("缺少线路记录，断点测算需要可排查的线路。")
    if not lamps:
        raise ValueError("缺少灯组记录，请登记在册灯组。")
    if not observations:
        raise ValueError("缺少夜巡观测记录，请登记同一时段的亮灭观测。")
    segment_switches = {}
    for switch in switches.values():
        segment_id = switch["segment_id"]
        if segment_id not in segments:
            raise ValueError(f"开关「{switch['switch_id']}」引用了不存在的线路「{segment_id}」。")
        if segment_id in segment_switches:
            raise ValueError(f"线路「{segment_id}」已有开关「{segment_switches[segment_id]}」，一条线路只登记一个开关。")
        segment_switches[segment_id] = switch["switch_id"]
    for observation in observations.values():
        if observation["site_id"] not in lamps:
            raise ValueError(f"观测的灯组「{observation['site_id']}」不在灯组记录中，请补录或更正。")
    return records


def build_model(records):
    """把规范化记录整理成可模拟的接线模型。"""
    model = {"sources": {}, "segments": {}, "lamps": {}, "observations": {}}
    switches = {}
    for record in records:
        kind = record["record_type"]
        if kind == SOURCE:
            model["sources"].setdefault(record["node"], []).append(record["source_id"])
        elif kind == SEGMENT:
            model["segments"][record["segment_id"]] = {
                "a": record["node_a"], "b": record["node_b"], "closed": True, "switch": None}
        elif kind == SWITCH:
            switches[record["switch_id"]] = record
        elif kind == LAMP:
            model["lamps"][record["site_id"]] = record["node"]
        elif kind == OBSERVATION:
            model["observations"][record["site_id"]] = record["observed"]
    for switch in switches.values():
        segment = model["segments"][switch["segment_id"]]
        segment["closed"] = switch["switch_state"] == CLOSED
        segment["switch"] = switch["switch_id"]
    for node in model["sources"]:
        model["sources"][node].sort()
    return model


def _adjacency(model):
    adj = {}
    for segment_id, segment in model["segments"].items():
        if not segment["closed"]:
            continue
        adj.setdefault(segment["a"], []).append((segment["b"], segment_id))
        adj.setdefault(segment["b"], []).append((segment["a"], segment_id))
    return adj


def _reach(adj, starts, broken):
    seen = set(starts)
    stack = list(starts)
    while stack:
        node = stack.pop()
        for neighbor, segment_id in adj.get(node, ()):
            if segment_id not in broken and neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return seen


class Search:
    """按断点数递增枚举候选线路组合，状态可序列化以便续算。"""

    def __init__(self, model, max_breaks, state=None, stop_early=False):
        self.model = model
        self.adj = _adjacency(model)
        self.source_nodes = sorted(model["sources"])
        self.lit = sorted(site for site, observed in model["observations"].items() if observed == LIT)
        self.dark = sorted(site for site, observed in model["observations"].items() if observed == DARK)
        self.stop_early = stop_early
        self.base_reach = _reach(self.adj, self.source_nodes, frozenset())
        # 亮灯在零断点下就不通电时，加断点也救不回来，整体无解。
        self.infeasible_lit = [site for site in self.lit if self.model["lamps"][site] not in self.base_reach]
        self.candidates = self._relevant()
        protected = self._protected()
        self.candidates = [segment for segment in self.candidates if segment not in protected]
        self.limit = min(max_breaks, len(self.candidates))
        self.display = []
        self.core = None
        self.union = set()
        self.total = 0
        self.visited = 0
        self.excluded = 0
        self.k = 0
        self.chosen = []
        self.frontier = [0]
        self.level_found = False
        if state:
            self.k = state["k"]
            self.chosen = list(state["chosen"])
            self.frontier = list(state["frontier"])
            self.display = [list(solution) for solution in state["display"]]
            self.core = None if state["core"] is None else list(state["core"])
            self.union = set(state["union"])
            self.total = state["total"]
            self.visited = state["visited"]
            self.excluded = state["excluded"]
            self.level_found = state["level_found"]

    def _relevant(self):
        """只保留落在某条到来灭灯组的线路：断在无关线路只会误伤亮灯。"""
        if not self.dark:
            return []
        relevant = set()
        for site in self.dark:
            toward = _reach(self.adj, [self.model["lamps"][site]], frozenset())
            for segment_id, segment in self.model["segments"].items():
                if not segment["closed"]:
                    continue
                a, b = segment["a"], segment["b"]
                if (a in self.base_reach and b in toward) or (b in self.base_reach and a in toward):
                    relevant.add(segment_id)
        return sorted(relevant)

    def _protected(self):
        """单独断开就会让亮灯组断电的线路，任何方案都不会选。"""
        protected = set()
        lamps = self.model["lamps"]
        for segment_id in self.candidates:
            reach = _reach(self.adj, self.source_nodes, frozenset((segment_id,)))
            if any(lamps[site] not in reach for site in self.lit):
                protected.add(segment_id)
        return protected

    def state(self):
        return {"k": self.k, "chosen": self.chosen, "frontier": self.frontier,
                "display": self.display, "core": self.core, "union": sorted(self.union),
                "total": self.total, "visited": self.visited, "excluded": self.excluded,
                "level_found": self.level_found}

    def _broken(self):
        return frozenset(self.candidates[index] for index in self.chosen)

    def _lit_ok(self):
        reach = _reach(self.adj, self.source_nodes, self._broken())
        lamps = self.model["lamps"]
        return all(lamps[site] in reach for site in self.lit)

    def _leaf(self):
        self.visited += 1
        reach = _reach(self.adj, self.source_nodes, self._broken())
        lamps = self.model["lamps"]
        if any(lamps[site] in reach for site in self.dark):
            return
        broken = self._broken()
        solution = sorted(broken)
        self.total += 1
        self.level_found = True
        self.union |= broken
        self.core = solution if self.core is None else [seg for seg in self.core if seg in broken]
        if len(self.display) < DISPLAY_SOLUTIONS:
            self.display.append(solution)

    def _pop(self):
        self.frontier.pop()
        if self.chosen:
            self.chosen.pop()

    def step(self, deadline, pulse=None):
        """推进枚举；时限内未完成返回 False，可凭 state() 续算。"""
        if self.infeasible_lit:
            return True
        count = len(self.candidates)
        while True:
            while self.frontier:
                if pulse:
                    pulse()
                if time.monotonic() >= deadline:
                    return False
                depth = len(self.chosen)
                if depth == self.k:
                    self._leaf()
                    if self.stop_early and self.total:
                        return True
                    self._pop()
                    continue
                index = self.frontier[-1]
                if count - index < self.k - depth:
                    self._pop()
                    continue
                self.frontier[-1] = index + 1
                self.chosen.append(index)
                if self._lit_ok():
                    self.frontier.append(index + 1)
                else:
                    # 已让某亮灯组断电的组合整枝排除，续算时凭进度跳过不重查。
                    self.excluded += comb(count - index - 1, self.k - depth - 1)
                    self.chosen.pop()
            if self.level_found:
                return True
            self.k += 1
            if self.k > self.limit:
                return True
            self.chosen = []
            self.frontier = [0]


class Discarder:
    """无解时按舍弃条数递增，找至少舍弃哪些观测才能算通。"""

    def __init__(self, model, state=None):
        self.model = model
        self.sites = sorted(model["observations"])
        self.d = 1
        self.next_index = 0
        self.found = []
        self.checked = 0
        self.proof = None
        if state:
            self.d = state["d"]
            self.next_index = state["next_index"]
            self.found = [list(combo) for combo in state["found"]]
            self.checked = state["checked"]

    def state(self):
        return {"d": self.d, "next_index": self.next_index, "found": self.found,
                "checked": self.checked}

    def _feasible(self, dropped, deadline, pulse):
        model = self.model
        sub = {**model, "observations": {site: observed for site, observed
                                         in model["observations"].items() if site not in dropped}}
        search = Search(sub, len(model["segments"]), stop_early=True)
        if search.infeasible_lit:
            return False
        if not search.step(deadline, pulse):
            raise _Deadline()
        return search.total > 0

    def step(self, deadline, pulse=None):
        total = len(self.sites)
        while self.d <= total:
            for position, combo in enumerate(combinations(range(total), self.d)):
                if position < self.next_index:
                    continue
                if pulse:
                    pulse()
                if time.monotonic() >= deadline:
                    self.next_index = position
                    return False
                dropped = {self.sites[index] for index in combo}
                self.checked += 1
                if self._feasible(dropped, deadline, pulse):
                    self.found.append(sorted(dropped))
                    if len(self.found) >= DISPLAY_DISCARDS:
                        self._prove()
                        return True
                self.next_index = position + 1
            if self.found:
                self._prove()
                return True
            self.d += 1
            self.next_index = 0
        self._prove()
        return True

    def _prove(self):
        """用第一套舍弃方案算出保留观测的最少断点，证明确实算得通。"""
        if not self.found:
            self.proof = {"kept": 0, "breakpoint_count": 0, "breakpoints": []}
            return
        dropped = set(self.found[0])
        model = self.model
        sub = {**model, "observations": {site: observed for site, observed
                                         in model["observations"].items() if site not in dropped}}
        search = Search(sub, len(model["segments"]), stop_early=True)
        search.step(time.monotonic() + 30)
        self.proof = {"kept": len(sub["observations"]),
                      "breakpoint_count": search.k if search.total else None,
                      "breakpoints": search.display[0] if search.display else []}


def _table(title, columns, rows):
    return {"title": title, "columns": [{"key": key, "label": label} for key, label in columns],
            "rows": rows}


def _segment_row(model, segment_id, membership):
    segment = model["segments"][segment_id]
    return {"segment_id": segment_id, "node_a": segment["a"], "node_b": segment["b"],
            "membership": membership}


def build_trace(model, solution):
    """逐灯复算一套方案：亮灯给出来电路径，灭灯给出切断它的断点。"""
    broken = set(solution)
    adj = _adjacency(model)
    parent = {}
    seen = set(model["sources"])
    queue = deque(sorted(model["sources"]))
    while queue:
        node = queue.popleft()
        for neighbor, segment_id in adj.get(node, ()):
            if segment_id in broken or neighbor in seen:
                continue
            seen.add(neighbor)
            parent[neighbor] = (node, segment_id)
            queue.append(neighbor)
    base_reach = _reach(adj, set(model["sources"]), frozenset())
    lamps = []
    for site in sorted(model["lamps"]):
        node = model["lamps"][site]
        observed = model["observations"].get(site)
        lit = node in seen
        if lit:
            hops = []
            cursor = node
            while cursor in parent:
                previous, segment_id = parent[cursor]
                hops.append((segment_id, cursor))
                cursor = previous
            hops.reverse()
            source_label = "、".join(model["sources"].get(cursor, ["?"]))
            witness = f"来电路径 {source_label}·{cursor}"
            for segment_id, hop_node in hops:
                witness += f" —{segment_id}→ {hop_node}"
        elif node not in base_reach:
            witness = "接线与开关记录下本就无来电路径"
        else:
            lamp_side = _reach(adj, [node], broken)
            cut = sorted(segment_id for segment_id in broken
                         if (model["segments"][segment_id]["a"] in lamp_side)
                         != (model["segments"][segment_id]["b"] in lamp_side))
            witness = f"断点 {'、'.join(cut)} 切断全部来路" if cut else "无到来电的完整路径"
        lamps.append({"site_id": site, "node": node, "observed": observed or "未观测",
                      "simulated": LIT if lit else DARK,
                      "match": "—" if observed is None else ("符合" if observed == (LIT if lit else DARK) else "不符"),
                      "witness": witness})
    return {"breakpoints": [_segment_row(model, segment_id, "") for segment_id in sorted(broken)],
            "lamps": lamps}


def _explained(model, search):
    core = sorted(search.core or [])
    optional = sorted(search.union - set(core))
    observed_total = len(model["observations"])
    solutions = [{"index": index, "breakpoints": list(solution), "count": len(solution)}
                 for index, solution in enumerate(search.display, start=1)]
    trace = build_trace(model, search.display[0])
    k = search.k
    stats = {"candidates": len(search.candidates), "visited": search.visited,
             "excluded": search.excluded}
    note = (f"候选线路 {len(search.candidates)} 条，检查组合 {search.visited} 组、"
            f"剪枝排除 {search.excluded} 组；最优方案共 {search.total} 套，"
            f"{'全部列出' if search.total <= DISPLAY_SOLUTIONS else f'展示前 {DISPLAY_SOLUTIONS} 套'}。")
    return {
        "verdict": "explained",
        "state": "ok" if k else "warning",
        "headline": (f"最少 {k} 处断点即可解释全部 {observed_total} 条夜巡观测。" if k
                     else f"无需断点，现有接线与开关记录即解释全部 {observed_total} 条夜巡观测。"),
        "note": note,
        "breakpoint_count": k,
        "solution_count": search.total,
        "core": [_segment_row(model, segment_id, "每套方案都含") for segment_id in core],
        "optional": [_segment_row(model, segment_id, "仅部分方案") for segment_id in optional],
        "solutions": solutions,
        "solutions_truncated": search.total > len(search.display),
        "trace": trace,
        "metrics": [
            {"label": "最少断点", "value": k, "detail": f"候选线路 {len(search.candidates)} 条"},
            {"label": "最优方案", "value": search.total,
             "detail": "全部枚举" if search.total <= DISPLAY_SOLUTIONS else f"展示前 {DISPLAY_SOLUTIONS} 套"},
            {"label": "每套方案都含", "value": len(core), "detail": "、".join(core) or "无"},
            {"label": "仅部分方案出现", "value": len(optional), "detail": "、".join(optional) or "无"},
            {"label": "检查组合", "value": search.visited, "detail": f"剪枝排除 {search.excluded} 组"},
        ],
        "tables": [
            _table("最优断点方案", (("index", "方案"), ("breakpoints_text", "断点线路"), ("count", "断点数")),
                   [{"index": item["index"], "breakpoints_text": "、".join(item["breakpoints"]) or "（无）",
                     "count": item["count"]} for item in solutions]),
            _table("断点归属", (("segment_id", "线路"), ("node_a", "节点甲"), ("node_b", "节点乙"),
                              ("membership", "出现范围")),
                   [_segment_row(model, segment_id, "每套方案都含") for segment_id in core]
                   + [_segment_row(model, segment_id, "仅部分方案") for segment_id in optional]),
            _table("方案一复算明细", (("site_id", "灯组"), ("node", "节点"), ("observed", "夜巡观测"),
                                    ("simulated", "复算结果"), ("match", "是否符合"), ("witness", "依据")),
                   trace["lamps"]),
        ],
        "sections": [{"title": "复算说明",
                      "text": "方案一的逐灯依据见「方案一复算明细」：亮灯给出来电路径，灭灯给出切断全部来路的断点。"
                              "在结果页的复算工具中任选断点组合，可按发起时的接线、开关和观测重新核对。"}],
        "stats": stats,
    }


def _over_limit(model, search, params):
    stats = {"candidates": len(search.candidates), "visited": search.visited,
             "excluded": search.excluded}
    return {
        "verdict": "over_limit",
        "state": "warning",
        "headline": f"在 {search.limit} 处断点上限内没有能解释全部 {len(model['observations'])} 条观测的方案。",
        "note": (f"候选线路 {len(search.candidates)} 条超过搜索上限，尚不能证明无解。"
                 f"请提高断点搜索上限后重新测算；已检查组合 {search.visited} 组、剪枝排除 {search.excluded} 组。"),
        "metrics": [
            {"label": "断点搜索上限", "value": search.limit, "detail": f"候选线路 {len(search.candidates)} 条"},
            {"label": "检查组合", "value": search.visited, "detail": f"剪枝排除 {search.excluded} 组"},
        ],
        "tables": [],
        "sections": [{"title": "下一步", "text": "提高断点搜索上限重新发起测算，或核对夜巡观测是否有误。"}],
        "stats": stats,
    }


def _unsat(model, discarder):
    observations = model["observations"]
    sets = [{"index": index,
             "drop": [{"site_id": site, "observed": observations[site]} for site in combo],
             "count": len(combo)}
            for index, combo in enumerate(discarder.found, start=1)]
    involved = sorted({site for combo in discarder.found for site in combo})
    proof = discarder.proof or {"kept": 0, "breakpoint_count": None, "breakpoints": []}
    d = len(discarder.found[0]) if discarder.found else 0
    stats = {"checked_discards": discarder.checked}
    proof_text = (f"舍弃「{'、'.join(discarder.found[0])}」后，保留 {proof['kept']} 条观测，"
                  f"最少 {proof['breakpoint_count']} 处断点（{'、'.join(proof['breakpoints']) or '无'}）即可算通。"
                  if discarder.found else "全部观测舍弃后按空观测算通。")
    return {
        "verdict": "unsat",
        "state": "warning",
        "headline": f"现有接线、开关记录无法解释全部 {len(observations)} 条观测，至少舍弃 {d} 条才能算通。",
        "note": f"共找到 {len(sets)} 套最少舍弃方案，涉及冲突观测 {len(involved)} 条。{proof_text}",
        "unsat": {"discard_count": d, "sets": sets, "involved": involved, "proof": proof},
        "metrics": [
            {"label": "夜巡观测", "value": len(observations), "detail": "同一时段记录"},
            {"label": "至少舍弃", "value": d, "detail": f"最少舍弃方案 {len(sets)} 套"},
            {"label": "涉及冲突观测", "value": len(involved), "detail": "、".join(involved) or "无"},
            {"label": "舍弃后断点", "value": proof["breakpoint_count"],
             "detail": "、".join(proof["breakpoints"]) or "无"},
        ],
        "tables": [
            _table("最少舍弃方案", (("index", "方案"), ("drop_text", "舍弃观测"), ("count", "舍弃条数")),
                   [{"index": item["index"],
                     "drop_text": "、".join(f"{drop['site_id']}（{drop['observed']}）" for drop in item["drop"]),
                     "count": item["count"]} for item in sets]),
        ],
        "sections": [{"title": "算通证明", "text": proof_text}],
        "stats": stats,
    }


def run_diagnosis(records, params, checkpoint, budget_seconds, pulse=None):
    """推进一轮求解。返回 (是否完成, 新进度, 结果)；未完成时凭进度续算。"""
    started = time.monotonic()
    deadline = started + max(1, int(budget_seconds))
    last_pulse = [started - 2]

    def beat():
        if pulse and time.monotonic() - last_pulse[0] >= 2:
            last_pulse[0] = time.monotonic()
            pulse()

    checkpoint = dict(checkpoint or {})
    prior_ms = float(checkpoint.get("elapsed_ms", 0))
    spent_ms = lambda: prior_ms + (time.monotonic() - started) * 1000
    model = build_model(validate_rows(records))
    phase = checkpoint.get("phase", "search")

    if phase == "search":
        search = Search(model, params["max_breaks"], checkpoint.get("search"))
        if not search.step(deadline, beat):
            return False, {"phase": "search", "search": search.state(), "elapsed_ms": spent_ms()}, None
        result = None
        if search.total:
            result = _explained(model, search)
        elif search.infeasible_lit or search.limit >= len(search.candidates):
            phase, checkpoint = "discard", {"phase": "discard"}
        else:
            result = _over_limit(model, search, params)
        if result is not None:
            result["stats"]["elapsed_ms"] = round(spent_ms())
            return True, {"phase": "done"}, result

    discarder = Discarder(model, checkpoint.get("discard"))
    try:
        finished = discarder.step(deadline, beat)
    except _Deadline:
        finished = False
    if not finished:
        return False, {"phase": "discard", "discard": discarder.state(), "elapsed_ms": spent_ms()}, None
    result = _unsat(model, discarder)
    result["stats"]["elapsed_ms"] = round(spent_ms())
    return True, {"phase": "done"}, result


def catalog(records):
    """供复算工具使用的接线目录：线路、开关、灯组和电源。"""
    model = build_model(validate_rows(records))
    return {
        "sources": [{"source_id": source_id, "node": node}
                    for node, ids in sorted(model["sources"].items()) for source_id in ids],
        "segments": [{"segment_id": segment_id, "node_a": segment["a"], "node_b": segment["b"],
                      "switch_id": segment["switch"],
                      "switch_state": CLOSED if segment["closed"] else OPEN}
                     for segment_id, segment in sorted(model["segments"].items())],
        "lamps": [{"site_id": site, "node": node,
                   "observed": model["observations"].get(site) or "未观测"}
                  for site, node in sorted(model["lamps"].items())],
    }


def verify(records, breakpoints):
    """按发起时的快照复算一组断点，返回逐灯结果和是否解释全部观测。"""
    model = build_model(validate_rows(records))
    unknown = sorted({item.strip().upper() for item in breakpoints if item.strip()}
                     - set(model["segments"]))
    if unknown:
        raise ValueError(f"断点线路不在记录中：{'、'.join(unknown)}。")
    broken = {item.strip().upper() for item in breakpoints if item.strip()}
    reach = _reach(_adjacency(model), set(model["sources"]), broken)
    lamps = []
    mismatches = []
    for site in sorted(model["lamps"]):
        observed = model["observations"].get(site)
        simulated = LIT if model["lamps"][site] in reach else DARK
        match = None if observed is None else observed == simulated
        if match is False:
            mismatches.append(site)
        lamps.append({"site_id": site, "node": model["lamps"][site],
                      "observed": observed or "未观测", "simulated": simulated,
                      "match": "—" if match is None else ("符合" if match else "不符")})
    return {"lamps": lamps, "breakpoint_count": len(broken), "breakpoints": sorted(broken),
            "observed_count": len(model["observations"]), "explained": not mismatches,
            "mismatches": mismatches}
