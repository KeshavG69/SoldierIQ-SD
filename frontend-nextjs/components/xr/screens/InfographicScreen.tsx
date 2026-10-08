"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Busy, C, MediaImage, SCREEN_W, SavedList, ScreenHeader, T, fmtDate, useScreenHandlers } from "../ui";
import { infographicApi } from "@/lib/api/infographic";
import { useDocumentStore } from "@/lib/stores/documentStore";

export default function InfographicScreen() {
  const [viewId, setViewId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedDocs = useDocumentStore((s) => s.selectedDocs);
  const queryClient = useQueryClient();

  const list = useQuery({ queryKey: ["infographics"], queryFn: infographicApi.list, enabled: !viewId });
  const generate = useMutation({
    mutationFn: () =>
      infographicApi.generate(Array.from(selectedDocs), { orientation: "landscape", detail_level: "standard", style: "auto" }),
    onSuccess: ({ workflow_id }) => {
      queryClient.invalidateQueries({ queryKey: ["infographics"] });
      setViewId(workflow_id);
    },
    onError: () => setError("Could not start infographic generation."),
  });

  if (viewId) return <InfographicViewer id={viewId} onExit={() => setViewId(null)} />;

  return (
    <group>
      <ScreenHeader title="Infographic" subtitle="Open one or generate a landscape infographic from your selected documents" />
      <SavedList
        items={(list.data ?? []).map((g) => ({
          id: g.workflow_id,
          title: g.title ?? "Untitled infographic",
          subtitle: g.status === "completed" ? fmtDate(g.created_at) : g.status === "processing" ? "generating…" : "failed",
          disabled: g.status === "failed",
        }))}
        loading={list.isLoading}
        onOpen={setViewId}
        onGenerate={() => {
          setError(null);
          generate.mutate();
        }}
        generating={generate.isPending}
        generateLabel="Generate infographic"
        canGenerate={selectedDocs.size > 0}
        emptyText="No infographics yet."
        error={error}
      />
    </group>
  );
}

function InfographicViewer({ id, onExit }: { id: string; onExit: () => void }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["infographic", id],
    queryFn: () => infographicApi.getById(id),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 4000 : false),
  });

  useScreenHandlers({
    back: () => {
      onExit();
      return true;
    },
  });

  const title = data?.title ?? "Infographic";
  return (
    <group>
      <ScreenHeader
        title={title}
        subtitle={data?.status === "completed" ? "Pinch with both hands and pull apart to enlarge" : undefined}
        onBack={onExit}
        backLabel="All images"
      />
      {isLoading || data?.status === "processing" ? (
        <Busy text="Designing your infographic… this takes a minute or two" />
      ) : isError || data?.status === "failed" || !data?.image_url ? (
        <T fontSize={0.02} color={C.danger} maxWidth={SCREEN_W - 0.1}>
          {data?.error || "This infographic could not be loaded."}
        </T>
      ) : (
        <MediaImage url={data.image_url} maxW={SCREEN_W - 0.06} maxH={0.54} position={[0, -0.05, 0.002]} />
      )}
    </group>
  );
}
