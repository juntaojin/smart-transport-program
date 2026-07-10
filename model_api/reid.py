import numpy as np
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════
# ReID 特征提取器 — 基于轻量 MobileNetV3-Small
# ═══════════════════════════════════════════════════════════════
class ReIDExtractor:
    def __init__(self, device="cuda"):
        import torch
        import torch.nn as nn
        from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
        from torchvision import transforms as T

        backbone = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1)
        backbone.classifier = nn.Identity()
        self.model = backbone
        self.model.to(device)
        self.model.eval()
        self.device = device
        self.feature_dim = 576

        self.transform = T.Compose([
            T.ToPILImage(),
            T.Resize((256, 128)),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    def extract_batch(self, crops):
        import torch
        import cv2
        from torchvision import transforms as T

        tensors = [self.transform(cv2.cvtColor(c, cv2.COLOR_BGR2RGB)) for c in crops]
        batch = torch.stack(tensors).to(self.device)
        with torch.no_grad():
            features = self.model(batch)
        features = features.cpu().numpy()
        norms = np.linalg.norm(features, axis=1, keepdims=True) + 1e-8
        return features / norms


# ═══════════════════════════════════════════════════════════════
# ID 合并器 — 基于 ReID 特征相似度 + 时空约束合并重复 ID
# ═══════════════════════════════════════════════════════════════
class IDMerger:
    def __init__(self, similarity_threshold=0.85, max_features_per_track=20,
                 max_distance=300, max_size_ratio=2.0):
        self.feature_gallery = defaultdict(list)
        self.id_mapping = {}
        self.next_merged_id = 1
        self.threshold = similarity_threshold
        self.max_features = max_features_per_track
        self.max_distance = max_distance
        self.max_size_ratio = max_size_ratio
        self.last_boxes = {}
        self.lost_frames = defaultdict(int)

    def update_batch(self, raw_ids, features, boxes):
        active_merged = set()
        for raw_id in raw_ids:
            raw_id = int(raw_id)
            if raw_id in self.id_mapping:
                active_merged.add(self.id_mapping[raw_id])

        merged_ids = []
        for raw_id, feat, box in zip(raw_ids, features, boxes):
            raw_id = int(raw_id)

            if raw_id in self.id_mapping:
                merged = self.id_mapping[raw_id]
                self._add_feature(merged, feat)
                self._update_position(merged, box)
                self.lost_frames[merged] = 0
                merged_ids.append(merged)
                continue

            best_id = self._find_best_match(feat, box, active_merged)

            if best_id is not None:
                self.id_mapping[raw_id] = best_id
                self._add_feature(best_id, feat)
                self._update_position(best_id, box)
                self.lost_frames[best_id] = 0
                merged_ids.append(best_id)
                active_merged.add(best_id)
            else:
                merged = self.next_merged_id
                self.next_merged_id += 1
                self.id_mapping[raw_id] = merged
                self._add_feature(merged, feat)
                self._update_position(merged, box)
                self.lost_frames[merged] = 0
                merged_ids.append(merged)
                active_merged.add(merged)

        for mid in list(self.lost_frames.keys()):
            if mid not in active_merged:
                self.lost_frames[mid] += 1

        return merged_ids

    def _find_best_match(self, new_feat, new_box, active_merged):
        best_id = None
        best_sim = -1.0

        nx = (new_box[0] + new_box[2]) / 2
        ny = (new_box[1] + new_box[3]) / 2
        nw = new_box[2] - new_box[0]
        nh = new_box[3] - new_box[1]

        for tid, feats in self.feature_gallery.items():
            if tid in active_merged:
                continue
            if not feats:
                continue

            if tid in self.last_boxes:
                lx, ly, lw, lh = self.last_boxes[tid]
                dist = np.sqrt((nx - lx) ** 2 + (ny - ly) ** 2)
                if dist > self.max_distance:
                    continue
                rw = max(nw, lw) / (min(nw, lw) + 1e-8)
                rh = max(nh, lh) / (min(nh, lh) + 1e-8)
                if rw > self.max_size_ratio or rh > self.max_size_ratio:
                    continue

            avg = np.mean(feats, axis=0)
            avg = avg / (np.linalg.norm(avg) + 1e-8)
            sim = float(np.dot(new_feat, avg))
            if sim > best_sim:
                best_sim = sim
                best_id = tid

        return best_id

    def _add_feature(self, track_id, feature):
        self.feature_gallery[track_id].append(feature)
        if len(self.feature_gallery[track_id]) > self.max_features:
            self.feature_gallery[track_id].pop(0)

    def _update_position(self, merged_id, box):
        cx = (box[0] + box[2]) / 2
        cy = (box[1] + box[3]) / 2
        w = box[2] - box[0]
        h = box[3] - box[1]
        self.last_boxes[merged_id] = (cx, cy, w, h)

    def get_display_id(self, raw_id):
        return self.id_mapping.get(int(raw_id), int(raw_id))
