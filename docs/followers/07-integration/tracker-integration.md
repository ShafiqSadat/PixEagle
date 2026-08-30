# Tracker Integration

> Connecting trackers to followers

---

## TrackerOutput Data Structure

The standard interface between trackers and followers:

```python
@dataclass
class TrackerOutput:
    # Required
    data_type: TrackerDataType
    timestamp: float

    # Position data (normalized -1 to +1)
    position_2d: Optional[Tuple[float, float]] = None
    position_3d: Optional[Tuple[float, float, float]] = None

    # Angular data (gimbal or bearing)
    angular: Optional[Tuple[float, ...]] = None  # 2D (bearing, elevation) or 3D gimbal (yaw_deg, pitch_deg, roll_deg)

    # Tracking metadata
    tracking_active: bool = False
    tracker_id: Optional[int] = None
    confidence: Optional[float] = None
    bbox: Optional[Tuple[int, int, int, int]] = None

    # Velocity estimation
    velocity: Optional[Tuple[float, float]] = None

    # Freshness/diagnostic metadata
    raw_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

---

## Data Types

```python
class TrackerDataType(Enum):
    POSITION_2D = "position_2d"
    POSITION_3D = "position_3d"
    GIMBAL_ANGLES = "gimbal_angles"
    BBOX_CONFIDENCE = "bbox_confidence"
    VELOCITY_AWARE = "velocity_aware"
    ANGULAR = "angular"
    MULTI_TARGET = "multi_target"
    EXTERNAL = "external"
```

---

## Coordinate Systems

### Image Coordinates (Raw)

```
(0,0) ──────────────────────► X (width)
  │
  │       ● Target (x_px, y_px)
  │
  ▼
  Y (height)
```

### Normalized Coordinates (TrackerOutput)

```
        (-1, -1)      (0, -1)       (+1, -1)
           ┌────────────┬────────────┐
           │            │            │
           │            │            │
(-1, 0) ───┼────────────●────────────┼─── (+1, 0)
           │         (0,0)           │
           │         Center          │
           │            │            │
           └────────────┴────────────┘
        (-1, +1)      (0, +1)       (+1, +1)
```

### Conversion

```python
def normalize_coordinates(x_px, y_px, width, height):
    """Convert pixel to normalized coordinates."""
    x_norm = (x_px / width) * 2 - 1   # [-1, +1]
    y_norm = (y_px / height) * 2 - 1  # [-1, +1]
    return x_norm, y_norm
```

---

## Tracker Types

### SmartTracker

YOLO + ByteTrack/BoT-SORT:

```python
from classes.smart_tracker import SmartTracker

tracker = SmartTracker()

# Update with frame
tracker_output = tracker.update(frame)

# Output includes confidence, bbox, velocity
```

### ClassicTracker

OpenCV trackers (CSRT, etc.):

```python
from classes.classic_tracker import ClassicTracker

tracker = ClassicTracker()
tracker.init(frame, roi)

tracker_output = tracker.update(frame)
```

### GimbalTracker

For gimbal-based tracking:

```python
# Gimbal angles instead of image position
tracker_output = TrackerOutput(
    data_type=TrackerDataType.GIMBAL_ANGLES,
    angular=(5.2, -2.1, 0.0),  # (yaw_deg, pitch_deg, roll_deg)
    tracking_active=True
)
```

---

## Follower Compatibility

### Check Requirements

```python
# Get required data types for follower
required = follower.get_required_tracker_data_types()
# [TrackerDataType.POSITION_2D]

# Validate compatibility
compatible = follower.validate_tracker_compatibility(tracker_output)
```

### Schema-Defined Requirements

In `follower_commands.yaml`:

```yaml
follower_profiles:
  mc_velocity_chase:
    required_tracker_data:
      - POSITION_2D
    optional_tracker_data:
      - BBOX_CONFIDENCE
      - VELOCITY_AWARE

  gm_velocity_chase:
    required_tracker_data:
      - GIMBAL_ANGLES
```

---

## Target Evidence And Command Authority

Do not use `tracking_active` alone as command evidence. The controller
normalizes tracker/video metadata including `usable_for_following`,
`data_is_stale`, `prediction_only`, identity ambiguity, frame
freshness, and follow-session generation into one
`TargetEvidenceSnapshot`.

Only confirmed evidence reaches follower command calculation. Non-confirmed
evidence bypasses followers and is evaluated by
`TargetContinuitySupervisor`. Predictions and stale positions remain
available for overlays and tracker reacquisition, but cannot independently
authorize pursuit commands.

The supervisor resolves strategy capabilities from `airframe_phase` and
`control_type`. The default requests immediate handoff. Qualified
bounded decay is currently limited to multicopter body-velocity command preview;
all unsupported or live combinations fail closed. See
[Target Continuity](../06-safety/target-continuity.md).

SmartTracker may emit `MULTI_TARGET` output while the selected identity
is stale, tentative, or prediction-only. Those candidates remain visible for
operator diagnostics, but do not regain authority until the selected identity
is continuously confirmed for the configured interval.

---

## Confidence Handling

### Confidence-Based Filtering

```python
if tracker_output.confidence is not None:
    if tracker_output.confidence < self.min_confidence:
        logger.warning(f"Low confidence: {tracker_output.confidence}")
        return False
```

### Velocity Scaling

```python
# Reduce velocity at low confidence
scale = min(1.0, tracker_output.confidence)
vel_fwd *= scale
vel_right *= scale
```

---

## Velocity-Aware Tracking

When tracker provides velocity estimates:

```python
if tracker_output.data_type == TrackerDataType.VELOCITY_AWARE:
    # Predictive following
    vx, vy = tracker_output.velocity
    predicted_x = tracker_output.position_2d[0] + vx * dt
    predicted_y = tracker_output.position_2d[1] + vy * dt
```

---

## Bounding Box Usage

### Distance Estimation

```python
# Larger bbox = closer target
if tracker_output.bbox:
    x, y, w, h = tracker_output.bbox
    bbox_area = w * h
    estimated_distance = calibration / sqrt(bbox_area)
```

### Size Tracking

```python
# Track target size changes
current_size = bbox_area
size_rate = (current_size - prev_size) / dt
```

---

## Integration Example

```python
class TrackingLoop:
    def __init__(self):
        self.px4 = PX4InterfaceManager()
        self.tracker = SmartTracker()
        self.follower = Follower(self.px4, (0, 0))
        self.commander = OffboardCommander(
            self.px4,
            self.follower.follower.setpoint_handler,
        )

    def run(self, frame):
        # Get tracker output
        tracker_output = self.tracker.update(frame)

        # Check tracking state
        if not tracker_output.tracking_active:
            self.handle_no_tracking()
            return

        # Execute following
        success = self.follower.follow_target(tracker_output)
        if success:
            self.commander.submit_intent(self.follower.get_last_command_intent())

        if not success:
            logger.warning("Following failed")
```
