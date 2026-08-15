"use client";

import { useEffect, useRef, useState } from "react";
import { useThemeStore } from "@/lib/stores/themeStore";

interface VideoClipViewerProps {
  videoUrl: string;
  filename: string;
  clipStart?: number;
  clipEnd?: number;
  onClose: () => void;
}

export default function VideoClipViewer({
  videoUrl,
  filename,
  clipStart,
  clipEnd,
  onClose,
}: VideoClipViewerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const theme = useThemeStore((state) => state.theme);
  const isDark = theme === 'dark';

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    let hasStarted = false;

    // Set initial time to clip start
    const initialize = () => {
      if (!hasStarted && clipStart !== undefined) {
        video.currentTime = clipStart;
        hasStarted = true;
        // Auto-play after setting start time
        video.play().catch(() => {
          // Auto-play might be blocked, that's okay
        });
      }
    };

    // Monitor playback and stop at clip end
    const handleTimeUpdate = () => {
      // If user seeks past the clip end or before clip start, reset to start
      if (clipStart !== undefined && clipEnd !== undefined) {
        if (video.currentTime >= clipEnd) {
          video.pause();
          video.currentTime = clipStart;
          setIsPlaying(false);
        } else if (video.currentTime < clipStart) {
          video.currentTime = clipStart;
        }
      }
    };

    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);

    // Wait for metadata to be loaded before setting currentTime
    const handleLoadedMetadata = () => {
      initialize();
    };

    if (video.readyState >= 1) {
      // Metadata already loaded
      initialize();
    } else {
      video.addEventListener('loadedmetadata', handleLoadedMetadata);
    }

    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('play', handlePlay);
    video.addEventListener('pause', handlePause);

    return () => {
      video.removeEventListener('loadedmetadata', handleLoadedMetadata);
      video.removeEventListener('timeupdate', handleTimeUpdate);
      video.removeEventListener('play', handlePlay);
      video.removeEventListener('pause', handlePause);
    };
  }, [clipStart, clipEnd]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === ' ' || e.key === 'Spacebar') {
        e.preventDefault();
        const video = videoRef.current;
        if (video) {
          if (video.paused) {
            video.play();
          } else {
            video.pause();
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-8">
      {/* Close button */}
      <button
        onClick={onClose}
        className="absolute top-6 right-6 p-2 hover:bg-white/10 rounded transition-colors group"
        title="Close (Esc)"
      >
        <svg
          className="w-6 h-6 text-white/70 group-hover:text-white"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M6 18L18 6M6 6l12 12"
          />
        </svg>
      </button>

      {/* Video container */}
      <div className="w-full max-w-6xl">
        {/* Header */}
        <div className="mb-4">
          <h2 className="text-xl font-semibold text-white mb-1">{filename}</h2>
          {clipStart !== undefined && clipEnd !== undefined && (
            <p className="text-sm text-white/60">
              Playing clip: {formatTime(clipStart)} - {formatTime(clipEnd)}
            </p>
          )}
        </div>

        {/* Video player */}
        <video
          ref={videoRef}
          className="w-full max-h-[70vh] bg-black rounded"
          controls
          src={videoUrl}
        >
          Your browser does not support the video tag.
        </video>

        {/* Instructions */}
        <div className="mt-4 text-center text-sm text-white/60">
          Press <kbd className="px-2 py-1 bg-white/10 rounded text-xs">Space</kbd> to play/pause,{' '}
          <kbd className="px-2 py-1 bg-white/10 rounded text-xs">Esc</kbd> to close
        </div>
      </div>
    </div>
  );
}
