import React from 'react';
import CenterFocusStrongIcon from '@mui/icons-material/CenterFocusStrong';
import ControlCameraIcon from '@mui/icons-material/ControlCamera';
import GrainIcon from '@mui/icons-material/Grain';
import SpeedIcon from '@mui/icons-material/Speed';
import TrackChangesIcon from '@mui/icons-material/TrackChanges';

const ICONS = Object.freeze({
  correlation: CenterFocusStrongIcon,
  external: ControlCameraIcon,
  optical_flow: GrainIcon,
  speed: SpeedIcon,
  track_changes: TrackChangesIcon,
});

const LEGACY_ICON_ALIASES = Object.freeze({
  '🎯': 'correlation',
  '⚡': 'speed',
  '📡': 'external',
  '🚀': 'speed',
});

const TrackerIcon = ({ icon, ...props }) => {
  const key = LEGACY_ICON_ALIASES[icon] || icon;
  const Icon = ICONS[key] || TrackChangesIcon;
  return <Icon {...props} />;
};

export default TrackerIcon;
