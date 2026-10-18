from typing import Literal
from pydantic import BaseModel, Field


class FrameInfo(BaseModel):
    frame_id: str
    acquired_at: str
    source: Literal['camera', 'file', 'demo', 'upload', 'view']
    width: int
    height: int
    raw_image: str | None = None
    camera_id: str | None = None


class BoundingBox(BaseModel):
    x: int
    y: int
    width: int
    height: int


class Center(BaseModel):
    x: float
    y: float


class CellDetection(BaseModel):
    frame_id: str
    detection_id: str
    label: Literal['defective', 'healthy']
    color: Literal['red', 'blue', 'green']
    bbox: BoundingBox
    center: Center
    area_px2: float
    touches_image_edge: bool
    printer_coordinates_mm: Center | None = None
    area_mm2: float | None = None
    calibration_id: str | None = None
    calibration_status: str = 'not_calibrated'


class CellCounts(BaseModel):
    defective: int
    healthy: int


class GridReference(BaseModel):
    cell_side_mm: float = 4.0
    source: Literal['user_provided'] = 'user_provided'
    used_for_calibration: bool = False


class ScanResult(BaseModel):
    schema_version: Literal['2.0'] = '2.0'
    ok: Literal[True] = True
    frame_id: str
    analysis_id: str
    frame: FrameInfo
    coordinate_space: Literal['image_pixels'] = 'image_pixels'
    pixel_origin: Literal['top_left'] = 'top_left'
    defective_color: Literal['red', 'blue'] = 'red'
    reference_grid: GridReference = Field(default_factory=GridReference)
    counts: CellCounts
    detections: list[CellDetection]
    annotated_image: str | None = None
    result_json: str | None = None
    method: str = 'HSV color segmentation and contour geometry'
    warnings: list[str] = Field(default_factory=list)
    calibration: dict | None = None


class ErrorResponse(BaseModel):
    ok: Literal[False] = False
    error: dict[str, str]
