from __future__ import annotations

from collections import deque
from enum import Enum

import numpy as np
from scipy.optimize import linear_sum_assignment

from ..config import TrackerConfig
from ..types import Detection
from .kalman import KalmanFilterXYAH


class TrackState(Enum):
    NEW = 0
    TRACKED = 1
    LOST = 2
    REMOVED = 3


def tlwh_to_xyah(tlwh: np.ndarray) -> np.ndarray:
    """[x, y, w, h] -> [cx, cy, aspect_ratio, h]"""
    ret = tlwh.copy()
    ret[:2] += ret[2:] / 2
    ret[2] /= ret[3]
    return ret


def xyxy_to_tlwh(bbox: np.ndarray) -> np.ndarray:
    return np.array(
        [bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]], dtype=np.float64
    )


def iou_distance(a_tracks: list[STrack], b_tracks: list[STrack]) -> np.ndarray:
    if not a_tracks or not b_tracks:
        return np.zeros((len(a_tracks), len(b_tracks)), dtype=np.float64)
    a = np.asarray([t.tlwh_to_xyxy(t.tlwh) for t in a_tracks])
    b = np.asarray([t.tlwh_to_xyxy(t.tlwh) for t in b_tracks])

    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    wh = np.clip(rb - lt, 0, None)
    inter = wh[:, :, 0] * wh[:, :, 1]
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    iou = np.where(union > 0, inter / np.maximum(union, 1e-6), 0.0)
    return 1.0 - iou


def fuse_score(cost: np.ndarray, detections: list[STrack]) -> np.ndarray:
    if cost.size == 0:
        return cost
    scores = np.array([d.score for d in detections], dtype=np.float64)
    return cost * (1.0 - scores[None, :])


class STrack:
    _next_id = 1
    history_maxlen = 60

    def __init__(self, tlwh: np.ndarray, score: float, class_id: int, class_name: str) -> None:
        self.tlwh = tlwh.astype(np.float64)
        self.score = score
        self.class_id = class_id
        self.class_name = class_name
        self.mean: np.ndarray | None = None
        self.covariance: np.ndarray | None = None
        self.state = TrackState.NEW
        self.track_id = 0
        self.frame_id = 0
        self.start_frame = 0
        self.tracklet_len = 0
        self.history: deque[tuple[float, float]] = deque(maxlen=STrack.history_maxlen)
        self.keypoints = None  # latest pose keypoints (pose backends)

    @staticmethod
    def tlwh_to_xyxy(tlwh: np.ndarray) -> np.ndarray:
        ret = tlwh.copy()
        ret[2:] += ret[:2]
        return ret

    @property
    def centroid(self) -> tuple[float, float]:
        return (float(self.tlwh[0] + self.tlwh[2] / 2), float(self.tlwh[1] + self.tlwh[3] / 2))

    @property
    def velocity(self) -> tuple[float, float]:
        if self.mean is None:
            return (0.0, 0.0)
        return (float(self.mean[4]), float(self.mean[5]))

    def activate(self, kf: KalmanFilterXYAH, frame_id: int) -> None:
        self.mean, self.covariance = kf.initiate(tlwh_to_xyah(self.tlwh))
        self.track_id = STrack._next_id
        STrack._next_id += 1
        self.state = TrackState.TRACKED
        self.frame_id = frame_id
        self.start_frame = frame_id
        self.tracklet_len = 0
        self.history.append(self.centroid)

    def predict(self, kf: KalmanFilterXYAH) -> None:
        if self.mean is None or self.covariance is None:
            return
        if self.state != TrackState.TRACKED:
            self.mean[7] = 0  # freeze height velocity when lost
        self.mean, self.covariance = kf.predict(self.mean, self.covariance)

    def update(self, kf: KalmanFilterXYAH, det: STrack, frame_id: int) -> None:
        assert self.mean is not None and self.covariance is not None
        self.mean, self.covariance = kf.update(
            self.mean, self.covariance, tlwh_to_xyah(det.tlwh)
        )
        xyah = self.mean[:4]
        w = xyah[2] * xyah[3]
        self.tlwh = np.array(
            [xyah[0] - w / 2, xyah[1] - xyah[3] / 2, w, xyah[3]], dtype=np.float64
        )
        self.score = det.score
        self.state = TrackState.TRACKED
        self.frame_id = frame_id
        self.tracklet_len += 1
        self.history.append(self.centroid)
        # class: "person" (0) is sticky — an object misdetection (e.g. a
        # person read as laptop) must not downgrade a person track.
        if det.class_id == 0 or self.class_id != 0:
            self.class_name = det.class_name
            self.class_id = det.class_id
        # keypoints: keep the last valid pose skeleton; object detections
        # have none and must not clear a person's skeleton.
        if det.keypoints is not None:
            self.keypoints = det.keypoints

    def mark_lost(self) -> None:
        self.state = TrackState.LOST

    def mark_removed(self) -> None:
        self.state = TrackState.REMOVED

    @classmethod
    def reset_ids(cls) -> None:
        cls._next_id = 1


class BYTETracker:
    """ByteTrack: two-round association (high-conf then low-conf detections)."""

    def __init__(self, cfg: TrackerConfig | None = None, frame_rate: int = 15) -> None:
        self.cfg = cfg or TrackerConfig()
        STrack.history_maxlen = self.cfg.history_size
        self.kf = KalmanFilterXYAH()
        self.frame_id = 0
        self.tracked: list[STrack] = []
        self.lost: list[STrack] = []
        self.removed: list[STrack] = []
        self.max_time_lost = self.cfg.max_time_lost or int(frame_rate * 2)
        self._buffer_size = int(frame_rate / 30.0 * self.cfg.max_time_lost) or self.cfg.max_time_lost

    def update(self, detections: list[Detection]) -> list[STrack]:
        self.frame_id += 1
        activated: list[STrack] = []
        refound: list[STrack] = []
        lost: list[STrack] = []
        removed: list[STrack] = []

        dets_high = [d for d in detections if d.score >= self.cfg.high_thresh]
        dets_low = [
            d for d in detections if self.cfg.low_thresh <= d.score < self.cfg.high_thresh
        ]

        stracks_high = [self._to_strack(d) for d in dets_high]
        stracks_low = [self._to_strack(d) for d in dets_low]

        unconfirmed = [t for t in self.tracked if t.tracklet_len == 0]
        tracked_stracks = [t for t in self.tracked if t.tracklet_len > 0]

        pool = tracked_stracks + self.lost
        for t in pool:
            t.predict(self.kf)

        # Round 1: high-confidence detections vs tracked+lost pool
        matches, u_track, u_det = self._match(pool, stracks_high, self.cfg.match_thresh, fuse=True)
        for i_pool, i_det in matches:
            track, det = pool[i_pool], stracks_high[i_det]
            if track.state == TrackState.TRACKED:
                track.update(self.kf, det, self.frame_id)
                activated.append(track)
            else:
                track.update(self.kf, det, self.frame_id)
                refound.append(track)

        # Round 2: remaining tracked vs low-confidence detections
        r_tracked = [pool[i] for i in u_track if pool[i].state == TrackState.TRACKED]
        matches, u_track2, _ = self._match(r_tracked, stracks_low, 0.5, fuse=False)
        for i_track, i_det in matches:
            track, det = r_tracked[i_track], stracks_low[i_det]
            track.update(self.kf, det, self.frame_id)
            activated.append(track)

        for i in u_track2:
            track = r_tracked[i]
            track.mark_lost()
            lost.append(track)

        # Unconfirmed tracks vs leftover high-conf detections
        leftover = [stracks_high[i] for i in u_det]
        matches, u_unconf, u_leftover = self._match(unconfirmed, leftover, 0.7)
        for i_track, i_det in matches:
            unconfirmed[i_track].update(self.kf, leftover[i_det], self.frame_id)
            activated.append(unconfirmed[i_track])
        for i in u_unconf:
            unconfirmed[i].mark_removed()
            removed.append(unconfirmed[i])

        # New tracks from remaining high-conf detections
        for i in u_leftover:
            det = leftover[i]
            det.activate(self.kf, self.frame_id)
            activated.append(det)

        # Purge long-lost tracks
        for track in list(self.lost):
            if self.frame_id - track.frame_id > self.max_time_lost:
                track.mark_removed()
                removed.append(track)

        self.tracked = [t for t in self.tracked if t.state == TrackState.TRACKED]
        self.tracked = self._merge(self.tracked, activated)
        self.tracked = self._merge(self.tracked, refound)
        self.lost = self._subtract(self.lost, self.tracked)
        self.lost = self._merge(self.lost, lost)
        self.lost = self._subtract(self.lost, self.removed)
        self.removed = self._merge(self.removed, removed)

        return [t for t in self.tracked if t.track_id != 0]

    @staticmethod
    def _to_strack(d: Detection) -> STrack:
        s = STrack(xyxy_to_tlwh(d.bbox), d.score, d.class_id, d.class_name)
        s.keypoints = getattr(d, "keypoints", None)
        return s

    def _match(
        self,
        tracks: list[STrack],
        dets: list[STrack],
        thresh: float,
        fuse: bool = False,
    ) -> tuple[list[tuple[int, int]], list[int], list[int]]:
        if not tracks or not dets:
            return [], list(range(len(tracks))), list(range(len(dets)))
        cost = iou_distance(tracks, dets)
        if fuse:
            cost = fuse_score(cost, dets)
        row, col = linear_sum_assignment(cost)
        matches: list[tuple[int, int]] = []
        u_track = set(range(len(tracks)))
        u_det = set(range(len(dets)))
        for r, c in zip(row, col):
            if cost[r, c] > thresh:
                continue
            matches.append((int(r), int(c)))
            u_track.discard(int(r))
            u_det.discard(int(c))
        return matches, sorted(u_track), sorted(u_det)

    @staticmethod
    def _merge(a: list[STrack], b: list[STrack]) -> list[STrack]:
        seen = {t.track_id for t in a}
        return a + [t for t in b if t.track_id not in seen]

    @staticmethod
    def _subtract(a: list[STrack], b: list[STrack]) -> list[STrack]:
        ids = {t.track_id for t in b}
        return [t for t in a if t.track_id not in ids]
