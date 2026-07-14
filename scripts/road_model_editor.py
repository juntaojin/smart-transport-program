from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


EXTENT_WIDTH = 1000
EXTENT_HEIGHT = 800
NODE_RADIUS = 7
POINT_RADIUS = 5
HIT_RADIUS = 12


@dataclass
class Node:
    id: str
    x: float
    y: float
    type: str
    name: str
    confidence: float


@dataclass
class Road:
    id: str
    from_node: str
    to_node: str
    name: str
    road_class: str
    lanes: int
    direction: str
    confidence: float
    centerline: list[list[float]] = field(default_factory=list)


@dataclass
class Lane:
    id: str
    road_id: str
    travel: str
    index: int
    confidence: float


class RoadModel:
    def __init__(self, folder: Path):
        self.folder = folder
        self.nodes: list[Node] = []
        self.roads: list[Road] = []
        self.lanes: list[Lane] = []
        self.metadata = {
            "name": "学校沙盘道路模型 v0.1",
            "coordinate_system": "normalized_schematic_xy",
            "extent": {"width": EXTENT_WIDTH, "height": EXTENT_HEIGHT},
            "units": "normalized_unit",
            "source": "manual_editor",
            "status": "preliminary",
            "notes": "由 road_model_editor.py 编辑保存。",
        }
        self.load()

    @property
    def node_by_id(self) -> dict[str, Node]:
        return {node.id: node for node in self.nodes}

    @property
    def road_by_id(self) -> dict[str, Road]:
        return {road.id: road for road in self.roads}

    def load(self) -> None:
        self.nodes = self._load_nodes_csv()
        self.roads = self._load_roads_csv()
        self.lanes = self._load_lanes_csv()
        json_path = self.folder / "road_model.json"
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8-sig"))
                self.metadata.update(data.get("metadata", {}))
            except Exception:
                pass

    def _load_nodes_csv(self) -> list[Node]:
        rows = read_csv(self.folder / "nodes.csv")
        return [
            Node(
                id=row["id"],
                x=float(row["x"]),
                y=float(row["y"]),
                type=row.get("type", ""),
                name=row.get("name", ""),
                confidence=float(row.get("confidence") or 0),
            )
            for row in rows
        ]

    def _load_roads_csv(self) -> list[Road]:
        rows = read_csv(self.folder / "roads.csv")
        roads: list[Road] = []
        for row in rows:
            centerline = json.loads(row.get("centerline") or "[]")
            roads.append(
                Road(
                    id=row["id"],
                    from_node=row.get("from", ""),
                    to_node=row.get("to", ""),
                    name=row.get("name", ""),
                    road_class=row.get("class", ""),
                    lanes=int(float(row.get("lanes") or 0)),
                    direction=row.get("direction", ""),
                    confidence=float(row.get("confidence") or 0),
                    centerline=[[float(x), float(y)] for x, y in centerline],
                )
            )
        return roads

    def _load_lanes_csv(self) -> list[Lane]:
        rows = read_csv(self.folder / "lanes.csv")
        return [
            Lane(
                id=row["id"],
                road_id=row.get("road_id", ""),
                travel=row.get("travel", ""),
                index=int(float(row.get("index") or 0)),
                confidence=float(row.get("confidence") or 0),
            )
            for row in rows
        ]

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self._save_nodes_csv()
        self._save_roads_csv()
        self._save_lanes_csv()
        self._save_json()

    def _save_nodes_csv(self) -> None:
        path = self.folder / "nodes.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["id", "x", "y", "type", "name", "confidence"])
            writer.writeheader()
            for node in self.nodes:
                writer.writerow(
                    {
                        "id": node.id,
                        "x": round(node.x, 3),
                        "y": round(node.y, 3),
                        "type": node.type,
                        "name": node.name,
                        "confidence": round(node.confidence, 4),
                    }
                )

    def _save_roads_csv(self) -> None:
        path = self.folder / "roads.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "id",
                    "from",
                    "to",
                    "name",
                    "class",
                    "lanes",
                    "direction",
                    "confidence",
                    "centerline",
                ],
            )
            writer.writeheader()
            for road in self.roads:
                writer.writerow(
                    {
                        "id": road.id,
                        "from": road.from_node,
                        "to": road.to_node,
                        "name": road.name,
                        "class": road.road_class,
                        "lanes": road.lanes,
                        "direction": road.direction,
                        "confidence": round(road.confidence, 4),
                        "centerline": json.dumps(
                            [[round(x, 3), round(y, 3)] for x, y in road.centerline],
                            ensure_ascii=False,
                        ),
                    }
                )

    def _save_lanes_csv(self) -> None:
        path = self.folder / "lanes.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["id", "road_id", "travel", "index", "confidence"])
            writer.writeheader()
            for lane in self.lanes:
                writer.writerow(
                    {
                        "id": lane.id,
                        "road_id": lane.road_id,
                        "travel": lane.travel,
                        "index": lane.index,
                        "confidence": round(lane.confidence, 4),
                    }
                )

    def _save_json(self) -> None:
        data = {
            "metadata": self.metadata,
            "nodes": [
                {
                    "id": node.id,
                    "x": round(node.x, 3),
                    "y": round(node.y, 3),
                    "type": node.type,
                    "name": node.name,
                    "confidence": round(node.confidence, 4),
                }
                for node in self.nodes
            ],
            "roads": [
                {
                    "id": road.id,
                    "from": road.from_node,
                    "to": road.to_node,
                    "name": road.name,
                    "class": road.road_class,
                    "lanes": road.lanes,
                    "direction": road.direction,
                    "confidence": round(road.confidence, 4),
                    "centerline": [[round(x, 3), round(y, 3)] for x, y in road.centerline],
                }
                for road in self.roads
            ],
            "lanes": [
                {
                    "id": lane.id,
                    "road_id": lane.road_id,
                    "travel": lane.travel,
                    "index": lane.index,
                    "confidence": round(lane.confidence, 4),
                }
                for lane in self.lanes
            ],
        }
        (self.folder / "road_model.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


class RoadModelEditor(tk.Tk):
    def __init__(self, model: RoadModel):
        super().__init__()
        self.title("学校沙盘道路模型编辑器")
        self.geometry("1320x900")
        self.minsize(1100, 720)
        self.model = model
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.selected_kind: str | None = None
        self.selected_id: str | None = None
        self.selected_point_index: int | None = None
        self.dragging = False
        self.show_grid = tk.BooleanVar(value=True)
        self.show_labels = tk.BooleanVar(value=True)
        self.snap_grid = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="")
        self.field_vars: dict[str, tk.StringVar] = {}
        self.field_setters = {}

        self._build_ui()
        self._bind_events()
        self.after(50, self.render)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="打开目录", command=self.open_folder).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="保存", command=self.save).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="重载", command=self.reload).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(toolbar, text="网格", variable=self.show_grid, command=self.render).pack(side=tk.LEFT)
        ttk.Checkbutton(toolbar, text="标签", variable=self.show_labels, command=self.render).pack(side=tk.LEFT)
        ttk.Checkbutton(toolbar, text="吸附10格", variable=self.snap_grid).pack(side=tk.LEFT)
        ttk.Label(toolbar, textvariable=self.status).pack(side=tk.RIGHT)

        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        canvas_frame = ttk.Frame(paned)
        self.canvas = tk.Canvas(canvas_frame, background="#f8fafc", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        paned.add(canvas_frame, weight=4)

        inspector = ttk.Frame(paned, padding=10)
        paned.add(inspector, weight=1)

        ttk.Label(inspector, text="属性", font=("", 13, "bold")).pack(anchor=tk.W)
        self.selection_label = ttk.Label(inspector, text="点击节点、道路或控制点开始编辑")
        self.selection_label.pack(anchor=tk.W, pady=(4, 12))

        self.form = ttk.Frame(inspector)
        self.form.pack(fill=tk.X)

        ttk.Separator(inspector).pack(fill=tk.X, pady=12)
        ttk.Label(inspector, text="操作", font=("", 11, "bold")).pack(anchor=tk.W)
        help_text = (
            "拖拽节点：移动路口并同步相连道路端点\n"
            "拖拽小圆点：修改道路中心线\n"
            "双击道路：插入控制点\n"
            "Delete：删除选中的道路控制点\n"
            "Ctrl+S：保存 CSV 和 JSON"
        )
        ttk.Label(inspector, text=help_text, justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 8))
        ttk.Button(inspector, text="删除控制点", command=self.delete_selected_point).pack(fill=tk.X)

        ttk.Separator(inspector).pack(fill=tk.X, pady=12)
        ttk.Label(inspector, text="道路列表", font=("", 11, "bold")).pack(anchor=tk.W)
        self.road_list = tk.Listbox(inspector, height=12, exportselection=False)
        self.road_list.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        for road in self.model.roads:
            self.road_list.insert(tk.END, f"{road.id}  {road.name}")
        self.road_list.bind("<<ListboxSelect>>", self.on_road_list_select)

    def _bind_events(self) -> None:
        self.canvas.bind("<Configure>", lambda _event: self.render())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.bind("<Delete>", lambda _event: self.delete_selected_point())
        self.bind("<Control-s>", lambda _event: self.save())

    def fit_transform(self) -> None:
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        margin = 40
        self.scale = min((width - margin * 2) / EXTENT_WIDTH, (height - margin * 2) / EXTENT_HEIGHT)
        self.scale = max(self.scale, 0.1)
        self.offset_x = (width - EXTENT_WIDTH * self.scale) / 2
        self.offset_y = (height - EXTENT_HEIGHT * self.scale) / 2

    def sx(self, x: float) -> float:
        return self.offset_x + x * self.scale

    def sy(self, y: float) -> float:
        return self.offset_y + y * self.scale

    def world(self, screen_x: float, screen_y: float) -> tuple[float, float]:
        x = (screen_x - self.offset_x) / self.scale
        y = (screen_y - self.offset_y) / self.scale
        return clamp(x, 0, EXTENT_WIDTH), clamp(y, 0, EXTENT_HEIGHT)

    def render(self) -> None:
        self.fit_transform()
        self.canvas.delete("all")
        self.draw_background()
        for road in self.model.roads:
            self.draw_road(road)
        for node in self.model.nodes:
            self.draw_node(node)
        self.draw_selected_controls()
        self.status.set(f"{self.model.folder}   节点 {len(self.model.nodes)} / 道路 {len(self.model.roads)}")

    def draw_background(self) -> None:
        x0, y0 = self.sx(0), self.sy(0)
        x1, y1 = self.sx(EXTENT_WIDTH), self.sy(EXTENT_HEIGHT)
        self.canvas.create_rectangle(x0, y0, x1, y1, fill="#ffffff", outline="#cbd5e1", width=2)
        if self.show_grid.get():
            for x in range(0, EXTENT_WIDTH + 1, 100):
                color = "#e2e8f0" if x else "#cbd5e1"
                self.canvas.create_line(self.sx(x), y0, self.sx(x), y1, fill=color)
                self.canvas.create_text(self.sx(x) + 2, y0 + 12, text=str(x), anchor=tk.W, fill="#64748b", font=("", 8))
            for y in range(0, EXTENT_HEIGHT + 1, 100):
                color = "#e2e8f0" if y else "#cbd5e1"
                self.canvas.create_line(x0, self.sy(y), x1, self.sy(y), fill=color)
                self.canvas.create_text(x0 + 4, self.sy(y) + 2, text=str(y), anchor=tk.NW, fill="#64748b", font=("", 8))

    def draw_road(self, road: Road) -> None:
        if len(road.centerline) < 2:
            return
        coords = []
        for x, y in road.centerline:
            coords.extend([self.sx(x), self.sy(y)])
        selected = self.selected_kind in {"road", "point"} and self.selected_id == road.id
        color = road_color(road.road_class)
        width = max(3, road.lanes * 2.4) * self.scale
        self.canvas.create_line(*coords, fill="#e2e8f0", width=width + 8 * self.scale, smooth=True, capstyle=tk.ROUND, joinstyle=tk.ROUND)
        self.canvas.create_line(*coords, fill=color, width=width, smooth=True, capstyle=tk.ROUND, joinstyle=tk.ROUND)
        if selected:
            self.canvas.create_line(*coords, fill="#f59e0b", width=max(2, width / 2), smooth=True, capstyle=tk.ROUND, joinstyle=tk.ROUND)
        if self.show_labels.get():
            mx, my = midpoint(road.centerline)
            self.canvas.create_text(self.sx(mx) + 8, self.sy(my) - 8, text=road.id, anchor=tk.W, fill="#334155", font=("", 9, "bold"))

    def draw_node(self, node: Node) -> None:
        r = NODE_RADIUS + (2 if self.selected_kind == "node" and self.selected_id == node.id else 0)
        fill = node_color(node.type)
        x, y = self.sx(node.x), self.sy(node.y)
        self.canvas.create_oval(x - r, y - r, x + r, y + r, fill=fill, outline="#ffffff", width=2)
        if self.show_labels.get():
            self.canvas.create_text(x + 10, y + 9, text=node.id, anchor=tk.W, fill="#0f172a", font=("", 9, "bold"))

    def draw_selected_controls(self) -> None:
        if self.selected_kind not in {"road", "point"} or not self.selected_id:
            return
        road = self.model.road_by_id.get(self.selected_id)
        if not road:
            return
        for index, (x, y) in enumerate(road.centerline):
            sr = POINT_RADIUS + (2 if self.selected_point_index == index else 0)
            sx, sy = self.sx(x), self.sy(y)
            self.canvas.create_oval(sx - sr, sy - sr, sx + sr, sy + sr, fill="#f8fafc", outline="#f97316", width=2)
            self.canvas.create_text(sx + 8, sy - 8, text=str(index), anchor=tk.W, fill="#ea580c", font=("", 8))

    def on_press(self, event: tk.Event) -> None:
        hit = self.hit_test(event.x, event.y)
        self.select_hit(hit)
        self.dragging = hit is not None

    def on_drag(self, event: tk.Event) -> None:
        if not self.dragging:
            return
        x, y = self.world(event.x, event.y)
        if self.snap_grid.get():
            x = round(x / 10) * 10
            y = round(y / 10) * 10
        if self.selected_kind == "node" and self.selected_id:
            node = self.model.node_by_id.get(self.selected_id)
            if node:
                old_x, old_y = node.x, node.y
                node.x, node.y = x, y
                self.sync_roads_after_node_move(node.id, old_x, old_y)
                self.populate_inspector()
        elif self.selected_kind == "point" and self.selected_id is not None and self.selected_point_index is not None:
            road = self.model.road_by_id.get(self.selected_id)
            if road and 0 <= self.selected_point_index < len(road.centerline):
                road.centerline[self.selected_point_index] = [x, y]
                self.sync_nodes_after_endpoint_move(road, self.selected_point_index, x, y)
                self.populate_inspector()
        self.render()

    def on_release(self, _event: tk.Event) -> None:
        self.dragging = False

    def on_double_click(self, event: tk.Event) -> None:
        road, segment_index, distance = self.nearest_road_segment(event.x, event.y)
        if not road or distance > HIT_RADIUS:
            return
        x, y = self.world(event.x, event.y)
        road.centerline.insert(segment_index + 1, [x, y])
        self.selected_kind = "point"
        self.selected_id = road.id
        self.selected_point_index = segment_index + 1
        self.populate_inspector()
        self.render()

    def hit_test(self, screen_x: float, screen_y: float) -> tuple[str, str, int | None] | None:
        for road in self.model.roads:
            if self.selected_id == road.id:
                for index, (x, y) in enumerate(road.centerline):
                    if distance(screen_x, screen_y, self.sx(x), self.sy(y)) <= HIT_RADIUS:
                        return ("point", road.id, index)
        for node in reversed(self.model.nodes):
            if distance(screen_x, screen_y, self.sx(node.x), self.sy(node.y)) <= HIT_RADIUS:
                return ("node", node.id, None)
        road, _segment_index, road_distance = self.nearest_road_segment(screen_x, screen_y)
        if road and road_distance <= HIT_RADIUS:
            return ("road", road.id, None)
        return None

    def nearest_road_segment(self, screen_x: float, screen_y: float) -> tuple[Road | None, int, float]:
        best: tuple[Road | None, int, float] = (None, -1, float("inf"))
        for road in self.model.roads:
            for index in range(len(road.centerline) - 1):
                ax, ay = road.centerline[index]
                bx, by = road.centerline[index + 1]
                dist = point_to_segment_distance(
                    screen_x,
                    screen_y,
                    self.sx(ax),
                    self.sy(ay),
                    self.sx(bx),
                    self.sy(by),
                )
                if dist < best[2]:
                    best = (road, index, dist)
        return best

    def select_hit(self, hit: tuple[str, str, int | None] | None) -> None:
        if hit is None:
            self.selected_kind = None
            self.selected_id = None
            self.selected_point_index = None
        else:
            self.selected_kind, self.selected_id, self.selected_point_index = hit
            if self.selected_kind == "road":
                self.selected_point_index = None
        self.populate_inspector()
        self.render()

    def populate_inspector(self) -> None:
        for child in self.form.winfo_children():
            child.destroy()
        self.field_vars.clear()
        self.field_setters.clear()
        if self.selected_kind == "node" and self.selected_id:
            node = self.model.node_by_id[self.selected_id]
            self.selection_label.config(text=f"节点 {node.id}")
            self.add_field("name", node.name, lambda v: setattr(node, "name", v))
            self.add_field("type", node.type, lambda v: setattr(node, "type", v))
            self.add_field("x", node.x, lambda v: setattr(node, "x", parse_float(v, node.x)))
            self.add_field("y", node.y, lambda v: setattr(node, "y", parse_float(v, node.y)))
            self.add_field("confidence", node.confidence, lambda v: setattr(node, "confidence", parse_float(v, node.confidence)))
        elif self.selected_kind in {"road", "point"} and self.selected_id:
            road = self.model.road_by_id[self.selected_id]
            title = f"道路 {road.id}"
            if self.selected_kind == "point" and self.selected_point_index is not None:
                title += f" / 控制点 {self.selected_point_index}"
            self.selection_label.config(text=title)
            self.add_field("name", road.name, lambda v: setattr(road, "name", v))
            self.add_field("class", road.road_class, lambda v: setattr(road, "road_class", v))
            self.add_field("lanes", road.lanes, lambda v: setattr(road, "lanes", max(1, int(parse_float(v, road.lanes)))))
            self.add_field("direction", road.direction, lambda v: setattr(road, "direction", v))
            self.add_field("confidence", road.confidence, lambda v: setattr(road, "confidence", parse_float(v, road.confidence)))
            if self.selected_kind == "point" and self.selected_point_index is not None:
                point = road.centerline[self.selected_point_index]
                self.add_field("point_x", point[0], lambda v: self.set_selected_point(0, v))
                self.add_field("point_y", point[1], lambda v: self.set_selected_point(1, v))
        else:
            self.selection_label.config(text="点击节点、道路或控制点开始编辑")

    def add_field(self, label: str, value: object, setter) -> None:
        row = ttk.Frame(self.form)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text=label, width=12).pack(side=tk.LEFT)
        var = tk.StringVar(value=str(value))
        self.field_vars[label] = var
        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry.bind("<Return>", lambda _event: self.apply_fields())
        entry.bind("<FocusOut>", lambda _event: self.apply_fields())
        self.field_setters[label] = setter

    def apply_fields(self) -> None:
        for label, var in self.field_vars.items():
            self.field_setters[label](var.get())
        self.render()

    def set_selected_point(self, axis: int, value: str) -> None:
        if not self.selected_id or self.selected_point_index is None:
            return
        road = self.model.road_by_id[self.selected_id]
        point = road.centerline[self.selected_point_index]
        point[axis] = parse_float(value, point[axis])
        self.sync_nodes_after_endpoint_move(road, self.selected_point_index, point[0], point[1])

    def sync_roads_after_node_move(self, node_id: str, old_x: float, old_y: float) -> None:
        for road in self.model.roads:
            if not road.centerline:
                continue
            if road.from_node == node_id:
                road.centerline[0] = [self.model.node_by_id[node_id].x, self.model.node_by_id[node_id].y]
            if road.to_node == node_id:
                road.centerline[-1] = [self.model.node_by_id[node_id].x, self.model.node_by_id[node_id].y]
            for point in road.centerline:
                if abs(point[0] - old_x) < 0.001 and abs(point[1] - old_y) < 0.001:
                    point[0] = self.model.node_by_id[node_id].x
                    point[1] = self.model.node_by_id[node_id].y

    def sync_nodes_after_endpoint_move(self, road: Road, point_index: int, x: float, y: float) -> None:
        nodes = self.model.node_by_id
        if point_index == 0 and road.from_node in nodes:
            nodes[road.from_node].x = x
            nodes[road.from_node].y = y
        if point_index == len(road.centerline) - 1 and road.to_node in nodes:
            nodes[road.to_node].x = x
            nodes[road.to_node].y = y

    def delete_selected_point(self) -> None:
        if self.selected_kind != "point" or self.selected_id is None or self.selected_point_index is None:
            return
        road = self.model.road_by_id.get(self.selected_id)
        if not road or len(road.centerline) <= 2:
            messagebox.showinfo("无法删除", "道路至少需要保留两个控制点。")
            return
        if self.selected_point_index in (0, len(road.centerline) - 1):
            messagebox.showinfo("无法删除", "端点由 from/to 节点控制，不能直接删除。")
            return
        del road.centerline[self.selected_point_index]
        self.selected_kind = "road"
        self.selected_point_index = None
        self.populate_inspector()
        self.render()

    def on_road_list_select(self, _event: tk.Event) -> None:
        selection = self.road_list.curselection()
        if not selection:
            return
        road = self.model.roads[selection[0]]
        self.selected_kind = "road"
        self.selected_id = road.id
        self.selected_point_index = None
        self.populate_inspector()
        self.render()

    def open_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=str(self.model.folder.parent), title="选择道路模型目录")
        if not folder:
            return
        try:
            self.model = RoadModel(Path(folder))
            self.selected_kind = None
            self.selected_id = None
            self.selected_point_index = None
            self.road_list.delete(0, tk.END)
            for road in self.model.roads:
                self.road_list.insert(tk.END, f"{road.id}  {road.name}")
            self.populate_inspector()
            self.render()
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def reload(self) -> None:
        try:
            self.model.load()
            self.selected_kind = None
            self.selected_id = None
            self.selected_point_index = None
            self.road_list.delete(0, tk.END)
            for road in self.model.roads:
                self.road_list.insert(tk.END, f"{road.id}  {road.name}")
            self.populate_inspector()
            self.render()
        except Exception as exc:
            messagebox.showerror("重载失败", str(exc))

    def save(self) -> None:
        try:
            self.apply_fields()
            self.model.save()
            messagebox.showinfo("保存完成", "已保存 nodes.csv、roads.csv、lanes.csv 和 road_model.json。")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))


def road_color(road_class: str) -> str:
    return {
        "arterial": "#2563eb",
        "collector": "#0f766e",
        "parking_loop": "#7c3aed",
        "urban_loop": "#db2777",
        "scenic_curve": "#16a34a",
        "curve": "#ea580c",
        "service": "#475569",
    }.get(road_class, "#334155")


def node_color(node_type: str) -> str:
    return {
        "boundary": "#ef4444",
        "intersection": "#10b981",
        "access": "#f59e0b",
    }.get(node_type, "#64748b")


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def point_to_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return distance(px, py, ax, ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = clamp(t, 0, 1)
    return distance(px, py, ax + t * dx, ay + t * dy)


def midpoint(points: list[list[float]]) -> tuple[float, float]:
    if not points:
        return 0, 0
    return points[len(points) // 2][0], points[len(points) // 2][1]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_float(value: str, fallback: float) -> float:
    try:
        return float(value)
    except ValueError:
        return fallback


def default_model_folder() -> Path:
    return Path(__file__).resolve().parents[1] / "testdata" / "学校沙盘道路模型_v0.1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="学校沙盘道路模型俯视图编辑器")
    parser.add_argument(
        "model_dir",
        nargs="?",
        default=str(default_model_folder()),
        help="包含 nodes.csv、roads.csv、lanes.csv 的模型目录",
    )
    args = parser.parse_args(argv)
    model_dir = Path(args.model_dir).resolve()
    if not model_dir.exists():
        print(f"模型目录不存在: {model_dir}", file=sys.stderr)
        return 1
    app = RoadModelEditor(RoadModel(model_dir))
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
