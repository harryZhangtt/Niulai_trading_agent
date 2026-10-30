import React from 'react';
import { createRoot } from 'react-dom/client';
import { NoticePreview } from '../src/Preview';
import '../src/styles.css';
import type { Notice } from './contracts';
const root = createRoot(document.getElementById('root')!);
(window as any).renderNoticePreview = (notice: Notice) => root.render(<NoticePreview notice={notice} />);
