import { create } from 'zustand';
import { GeneratedDocument } from '@/types';

// Right-hand preview pane for files the agent built (port of enterprise's
// file-preview-store). Opening a preview hides the workflow panel; "expanded"
// gives the pane the whole width, hiding the chat too.
type FilePreviewStore = {
  isOpen: boolean;
  doc: GeneratedDocument | null;
  isExpanded: boolean;
  openPreview: (doc: GeneratedDocument) => void;
  closePreview: () => void;
  toggleExpanded: () => void;
};

export const useFilePreviewStore = create<FilePreviewStore>((set) => ({
  isOpen: false,
  doc: null,
  isExpanded: false,
  openPreview: (doc) => set({ isOpen: true, doc }),
  closePreview: () => set({ isOpen: false, doc: null, isExpanded: false }),
  toggleExpanded: () => set((s) => ({ isExpanded: !s.isExpanded })),
}));
