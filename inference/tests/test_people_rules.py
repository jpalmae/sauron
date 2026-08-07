import numpy as np

from sauron_inference.rules.occupancy import classify_posture


def _kp(hip, knee, ankle, conf=0.9):
    kp = np.zeros((17, 3))
    for i, (x, y) in [(11, hip), (13, knee), (15, ankle), (12, hip), (14, knee), (16, ankle)]:
        kp[i] = [x, y, conf]
    return kp


def test_standing_posture():
    # pierna recta: cadera-rodilla-tobillo alineados (ángulo ~180°)
    kp = _kp(hip=(100, 100), knee=(100, 200), ankle=(100, 300))
    assert classify_posture(kp, (80, 50, 120, 350)) == "standing"


def test_sitting_posture():
    # rodilla doblada: tobillo detrás de la rodilla (ángulo ~90°)
    kp = _kp(hip=(100, 100), knee=(100, 200), ankle=(50, 200))
    assert classify_posture(kp, (60, 60, 180, 280)) == "sitting"


def test_fallen_by_aspect_ratio():
    # bbox más ancho que alto -> persona caída, sin importar keypoints
    assert classify_posture(None, (0, 0, 300, 100)) == "fallen"


def test_unknown_without_confident_keypoints():
    kp = _kp(hip=(100, 100), knee=(100, 200), ankle=(100, 300), conf=0.1)
    assert classify_posture(kp, (80, 50, 120, 350)) == "unknown"


def test_unknown_without_keypoints_or_bbox():
    assert classify_posture(None, None) == "unknown"
