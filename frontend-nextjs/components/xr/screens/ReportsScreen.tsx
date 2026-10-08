"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Busy, Button, C, SCREEN_H, SCREEN_W, SavedList, ScreenHeader, T, paginate, usePager, useScreenHandlers } from "../ui";
import { readReportStream, reportsApi } from "@/lib/api/reports";
import { HARDCODED_FORMATS } from "@/lib/constants/reportFormats";
import { useDocumentStore } from "@/lib/stores/documentStore";
import { useXRUi } from "@/lib/stores/xrUiStore";

interface Format {
  id: string;
  name: string;
  description: string;
  prompt: string;
}

export default function ReportsScreen() {
  const [report, setReport] = useState<{ title: string; content: string } | null>(null);
  if (report) return <ReportReader title={report.title} content={report.content} onExit={() => setReport(null)} />;
  return <PickFormat onReady={setReport} />;
}

function PickFormat({ onReady }: { onReady: (r: { title: string; content: string }) => void }) {
  const selectedDocs = useDocumentStore((s) => s.selectedDocs);
  const setScreen = useXRUi((s) => s.setScreen);
  const documentIds = useMemo(() => Array.from(selectedDocs), [selectedDocs]);
  const triggered = useRef<string | null>(null);

  // AI-suggested formats for this document set (generated in the background, then polled).
  const suggestions = useQuery({
    queryKey: ["reportSuggestions", documentIds],
    enabled: documentIds.length > 0,
    queryFn: () => reportsApi.getSuggestions(documentIds),
    refetchInterval: (query) => (query.state.data?.status === "processing" || query.state.data?.status === "not_found" ? 2500 : false),
  });
  useEffect(() => {
    const key = documentIds.join(",");
    if (suggestions.data?.status === "not_found" && triggered.current !== key) {
      triggered.current = key;
      void reportsApi.triggerFormatSuggestions(documentIds).catch(() => {});
    }
  }, [suggestions.data?.status, documentIds]);

  const formats: Format[] = useMemo(
    () => [
      ...(suggestions.data?.suggestions ?? []).map((s, i) => ({ id: `ai-${i}`, ...s })),
      ...HARDCODED_FORMATS,
    ],
    [suggestions.data],
  );

  const generate = useMutation({
    mutationFn: async (format: Format) => {
      const stream = await reportsApi.generateReport(documentIds, format.prompt);
      return { title: `${format.name} report`, content: await readReportStream(stream) };
    },
    onSuccess: onReady,
  });

  if (documentIds.length === 0) {
    return (
      <group>
        <ScreenHeader title="Reports" />
        <NoDocs onPick={() => setScreen("documents")} />
      </group>
    );
  }

  const loadingAi = suggestions.data?.status === "processing" || suggestions.data?.status === "not_found";
  return (
    <group>
      <ScreenHeader
        title="Reports"
        subtitle={loadingAi ? "Pick a format · AI suggestions are on the way…" : "Pick a format to write a report from your selected documents"}
      />
      {generate.isPending ? (
        <Busy text={`Writing your ${generate.variables?.name ?? ""} report… this can take a minute`} />
      ) : (
        <SavedList
          items={formats.map((f) => ({ id: f.id, title: f.name, subtitle: f.description }))}
          onOpen={(id) => {
            const f = formats.find((x) => x.id === id);
            if (f) generate.mutate(f);
          }}
          canGenerate
          emptyText="No formats available."
          error={generate.isError ? (generate.error as Error).message : null}
        />
      )}
    </group>
  );
}

function NoDocs({ onPick }: { onPick: () => void }) {
  useScreenHandlers({});
  return (
    <group>
      <T position={[0, 0.04, 0]} fontSize={0.022} color={C.muted}>
        Select documents first.
      </T>
      <Button label="Select documents" width={0.26} color={C.accent} position={[0, -0.05, 0]} onClick={onPick} />
    </group>
  );
}

function ReportReader({ title, content, onExit }: { title: string; content: string; onExit: () => void }) {
  const pages = useMemo(() => paginate(content, 1500), [content]);
  const pager = usePager(pages.length, content);

  useScreenHandlers({ next: pager.next, prev: pager.prev, back: () => (onExit(), true) });

  return (
    <group>
      <ScreenHeader title={title} subtitle={`Page ${pager.page + 1} of ${pages.length} · swipe to turn pages`} onBack={onExit} backLabel="Formats" />
      <T
        position={[-SCREEN_W / 2 + 0.05, SCREEN_H / 2 - 0.13, 0]}
        anchorX="left"
        anchorY="top"
        fontSize={0.0165}
        lineHeight={1.4}
        maxWidth={SCREEN_W - 0.1}
      >
        {pages[pager.page]}
      </T>
      <Button label="<" width={0.06} position={[-SCREEN_W / 2 + 0.06, -SCREEN_H / 2 + 0.04, 0]} disabled={pager.page === 0} onClick={pager.prev} />
      <Button label=">" width={0.06} position={[SCREEN_W / 2 - 0.06, -SCREEN_H / 2 + 0.04, 0]} disabled={pager.page >= pages.length - 1} onClick={pager.next} />
    </group>
  );
}
