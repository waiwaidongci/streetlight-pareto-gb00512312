"""临汀市虚拟接线、开关记录与 11 月 21 日夜巡观测。

演示拓扑：箱变 P-01 经 N1 供电，N4 由 N2、N3 两路环网供电，N7 挂在
N2—N6—N7 串行链路上，N8 的线路开关 SW-08 记录为断开。首批观测中
LH-04 漏记；补录批次补登 LH-04 为亮，与 LH-03 的灭观测冲突。
"""

_SOURCE = ("P-01", "N1")

_SEGMENTS = (
    ("SEG-01", "N1", "N2"),
    ("SEG-02", "N2", "N3"),
    ("SEG-03", "N3", "N4"),
    ("SEG-04", "N2", "N4"),
    ("SEG-05", "N4", "N5"),
    ("SEG-06", "N6", "N7"),
    ("SEG-07", "N2", "N6"),
    ("SEG-08", "N3", "N8"),
)

_SWITCHES = (("SW-08", "SEG-08", "断开"),)

_LAMPS = (
    ("LH-01", "N2"),
    ("LH-02", "N3"),
    ("LH-03", "N4"),
    ("LH-04", "N5"),
    ("LH-05", "N7"),
    ("LH-06", "N8"),
)

_OBSERVED = {"LH-01": "亮", "LH-02": "亮", "LH-03": "灭", "LH-05": "灭", "LH-06": "灭"}
_SUPPLEMENT = {"LH-04": "亮"}


def _rows(observations):
    rows = [{"record_type": "电源点", "source_id": _SOURCE[0], "segment_id": None, "switch_id": None,
             "site_id": None, "node_a": _SOURCE[1], "node_b": None, "switch_state": None, "observed": None}]
    rows += [{"record_type": "线路", "source_id": None, "segment_id": segment_id, "switch_id": None,
              "site_id": None, "node_a": node_a, "node_b": node_b, "switch_state": None, "observed": None}
             for segment_id, node_a, node_b in _SEGMENTS]
    rows += [{"record_type": "开关", "source_id": None, "segment_id": segment_id, "switch_id": switch_id,
              "site_id": None, "node_a": None, "node_b": None, "switch_state": state, "observed": None}
             for switch_id, segment_id, state in _SWITCHES]
    rows += [{"record_type": "灯组", "source_id": None, "segment_id": None, "switch_id": None,
              "site_id": site_id, "node_a": node, "node_b": None, "switch_state": None, "observed": None}
             for site_id, node in _LAMPS]
    rows += [{"record_type": "观测", "source_id": None, "segment_id": None, "switch_id": None,
              "site_id": site_id, "node_a": None, "node_b": None, "switch_state": None, "observed": observed}
             for site_id, observed in observations.items()]
    return rows


def circuit_rows():
    """首批记录：LH-04 当班漏记，其余五组有同一时段观测。"""
    return _rows(_OBSERVED)


def supplement_rows():
    """补录批次：补登 LH-04 为亮，与 LH-03 的灭观测无法同时成立。"""
    return _rows({**_OBSERVED, **_SUPPLEMENT})
