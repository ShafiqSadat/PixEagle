import React from 'react';
import { IconButton, Tooltip } from '@mui/material';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';

export const PIXEAGLE_DOCS = Object.freeze({
  classicTrackers: 'https://github.com/alireza787b/PixEagle/blob/main/docs/trackers/02-reference/README.md',
  smartModels: 'https://github.com/alireza787b/PixEagle/blob/main/docs/MODEL_CATALOG.md',
  followers: 'https://github.com/alireza787b/PixEagle/blob/main/docs/followers/02-reference/README.md',
});

const DocumentationLink = ({ href, label }) => (
  <Tooltip title={label}>
    <IconButton
      component="a"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      size="small"
      aria-label={label}
      sx={{ width: 28, height: 28 }}
    >
      <InfoOutlinedIcon sx={{ fontSize: 18 }} />
    </IconButton>
  </Tooltip>
);

export default DocumentationLink;
