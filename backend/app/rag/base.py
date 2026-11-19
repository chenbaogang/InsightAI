from dataclasses import dataclass, field


@dataclass
class VecItem:
    id: str
    ns: str
    text: str
    metadata: dict = field(default_factory=dict)
    vector: list[float] = field(default_factory=list)


@dataclass
class VecHit:
    id: str
    ns: str
    score: float
    text: str
    metadata: dict

