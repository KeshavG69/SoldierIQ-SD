"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/stores/authStore";
import { useChatStore } from "@/lib/stores/chatStore";
import { useVoiceStore } from "@/lib/stores/voiceStore";
import ModelSelector from "./ModelSelector";
import WorkspaceSwitcher from "./WorkspaceSwitcher";
import ThemeToggle from "../ThemeToggle";
import SessionDropdown from "./SessionDropdown";
import TicketCreationModal from "../TicketCreationModal";
import TeamModal from "./TeamModal";
import ConnectorsModal from "./ConnectorsModal";
import MemoryModal from "./MemoryModal";
import { Z_INDEX } from "@/lib/constants/zIndex";

export default function Header() {
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const { messages } = useChatStore();
  const [showMenu, setShowMenu] = useState(false);
  const [showTicketModal, setShowTicketModal] = useState(false);
  const [showTeam, setShowTeam] = useState(false);
  const [showConnectors, setShowConnectors] = useState(false);
  const [showMemory, setShowMemory] = useState(false);
  const voiceState = useVoiceStore((s) => s.state);
  const startCall = useVoiceStore((s) => s.start);
  const callBusy = voiceState === "fetching-token" || voiceState === "connected";

  const handleLogout = async () => {
    await logout();
    router.push("/auth/login");
  };

  const startAgentChat = () => {
    startCall({ document_ids: [], file_names: [], mode: "concierge" });
  };

  const openCalendly = () => {
    const calendlyUrl = "https://calendly.com/soldieriq-io/30min";
    if (typeof window !== "undefined" && window.Calendly) {
      window.Calendly.initPopupWidget({ url: calendlyUrl });
    }
  };

  const hasUserMessages = messages.some((msg) => msg.role === "user");

  const navBtnClass =
    "inline-flex items-center gap-1.5 px-3 h-8 rounded-lg text-xs font-medium text-muted-foreground dark:text-foreground hover:text-foreground dark:hover:text-white hover:bg-secondary dark:hover:bg-accent transition-colors";

  return (
    <header className="min-h-14 xl:h-14 py-2 xl:py-0 bg-white dark:bg-[#0a0a0a] border-b border-border dark:border-border flex flex-wrap xl:flex-nowrap items-center justify-between gap-x-4 gap-y-2 px-4 relative z-30">
      {/* The left controls plus the right buttons are ~1100px wide (~1500px
          with labels), so below xl the groups wrap onto extra rows instead of
          overlapping, and the right buttons show labels only at 2xl. */}
      <div className="flex flex-wrap xl:flex-nowrap items-center gap-x-4 gap-y-2 min-w-0">
        {/* Logo */}
        <div className="flex items-center gap-2.5 flex-shrink-0">
          <div className="w-7 h-7 rounded-md bg-brand flex items-center justify-center shadow-accent">
            <svg
              className="w-4 h-4 text-brand-foreground"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
          </div>
          <span className="text-sm font-semibold tracking-tight text-foreground dark:text-foreground">
            SoldierIQ
          </span>
        </div>

        <div className="hidden xl:block h-5 w-px bg-secondary dark:bg-secondary" />

        {/* Organization switcher */}
        <WorkspaceSwitcher />

        <div className="hidden xl:block h-5 w-px bg-secondary dark:bg-secondary" />

        {/* Model Selector */}
        <ModelSelector />

        {/* Session Dropdown */}
        <SessionDropdown hasUserMessages={hasUserMessages} />
      </div>

      <div className="flex items-center gap-1 flex-shrink-0 ml-auto">
        <button
          onClick={() => setShowConnectors(true)}
          className={navBtnClass}
          title="Connect apps and TAK"
          aria-label="Connectors"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 22v-5M9 8V2M15 8V2M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z" />
          </svg>
          <span className="hidden 2xl:inline">Connectors</span>
        </button>

        <button onClick={() => setShowTicketModal(true)} className={navBtnClass} title="New ticket" aria-label="New ticket">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 5v2m0 4v2m0 4v2M5 5a2 2 0 00-2 2v3a2 2 0 110 4v3a2 2 0 002 2h14a2 2 0 002-2v-3a2 2 0 110-4V7a2 2 0 00-2-2H5z" />
          </svg>
          <span className="hidden 2xl:inline">New ticket</span>
        </button>

        <button
          onClick={startAgentChat}
          disabled={callBusy}
          className={`${navBtnClass} disabled:opacity-40 disabled:cursor-not-allowed`}
          title="Talk to the SoldierIQ concierge (video avatar)"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
          </svg>
          <span className="hidden 2xl:inline">Agent chat</span>
        </button>

        <button onClick={openCalendly} className={navBtnClass} title="Book call" aria-label="Book call">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="4" width="18" height="18" rx="2" />
            <path d="M16 2v4M8 2v4M3 10h18" />
          </svg>
          <span className="hidden 2xl:inline">Book call</span>
        </button>

        <button onClick={() => router.push("/dashboard/xr")} className={navBtnClass} title="Voice agent with hand gestures (Meta Quest)">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 8a2 2 0 012-2h14a2 2 0 012 2v7a2 2 0 01-2 2h-4l-2-3h-2l-2 3H5a2 2 0 01-2-2V8z" />
          </svg>
          <span className="hidden 2xl:inline">VR mode</span>
        </button>

        <div className="mx-1 h-5 w-px bg-secondary dark:bg-secondary" />

        <ThemeToggle />

        <div className="relative">
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setShowMenu((prev) => !prev);
            }}
            className="flex items-center gap-2 pl-1.5 pr-2.5 h-9 rounded-lg hover:bg-secondary dark:hover:bg-accent transition-colors"
          >
            <div className="w-6 h-6 rounded-full bg-card dark:bg-secondary text-white dark:text-foreground text-[11px] font-semibold flex items-center justify-center">
              {user?.email?.charAt(0).toUpperCase()}
            </div>
            <span className="hidden sm:inline text-xs font-medium text-muted-foreground dark:text-foreground max-w-[140px] truncate">
              {user?.email}
            </span>
            <svg
              className={`w-3.5 h-3.5 text-muted-foreground transition-transform ${showMenu ? "rotate-180" : ""}`}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>

          {showMenu && (
            <>
              <div
                className="fixed inset-0"
                style={{ zIndex: Z_INDEX.DROPDOWN }}
                onClick={(e) => {
                  e.stopPropagation();
                  setShowMenu(false);
                }}
              />
              <div
                className="absolute right-0 top-full mt-1.5 w-56 rounded-xl bg-white dark:bg-background border border-border dark:border-border shadow-xl overflow-hidden"
                style={{ zIndex: Z_INDEX.DROPDOWN + 1 }}
              >
                <div className="px-3 py-2.5 border-b border-border dark:border-border">
                  <div className="text-[11px] text-muted-foreground">Signed in as</div>
                  <div className="text-xs font-medium text-foreground dark:text-foreground truncate">
                    {user?.email}
                  </div>
                </div>
                <div className="p-1">
                  <button
                    onClick={() => {
                      setShowMenu(false);
                      setShowTeam(true);
                    }}
                    className="w-full flex items-center gap-2 px-2.5 py-2 text-left text-sm text-muted-foreground dark:text-foreground hover:bg-secondary dark:hover:bg-accent rounded-lg transition-colors"
                  >
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 7a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
                    </svg>
                    Organization
                  </button>
                  <button
                    onClick={() => {
                      setShowMenu(false);
                      setShowMemory(true);
                    }}
                    className="w-full flex items-center gap-2 px-2.5 py-2 text-left text-sm text-muted-foreground dark:text-foreground hover:bg-secondary dark:hover:bg-accent rounded-lg transition-colors"
                  >
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18ZM12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18ZM12 5v13" />
                    </svg>
                    Memory
                  </button>
                  <button
                    onClick={() => {
                      setShowMenu(false);
                      handleLogout();
                    }}
                    className="w-full flex items-center gap-2 px-2.5 py-2 text-left text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 rounded-lg transition-colors"
                  >
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
                    </svg>
                    Sign out
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {showTicketModal && <TicketCreationModal onClose={() => setShowTicketModal(false)} />}
      {showTeam && <TeamModal onClose={() => setShowTeam(false)} />}
      {showConnectors && <ConnectorsModal onClose={() => setShowConnectors(false)} />}
      {showMemory && <MemoryModal onClose={() => setShowMemory(false)} />}
    </header>
  );
}
