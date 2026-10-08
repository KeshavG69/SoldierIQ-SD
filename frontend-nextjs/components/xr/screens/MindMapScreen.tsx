"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Line } from "@react-three/drei";

import { Busy, Button, C, Panel, SCREEN_H, SCREEN_W, SavedList, ScreenHeader, T, fmtDate, usePager, useScreenHandlers } from "../ui";
import { mindmapApi, type MindMapResponse } from "@/lib/api/mindmap";
import { useDocumentStore } from "@/lib/stores/documentStore";
import { useXRUi } from "@/lib/stores/xrUiStore";

export default function MindMapScreen() {
  const [map, setMap] = useState<MindMapResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedDocs = useDocumentStore((s) => s.selectedDocs);
  const queryClient = useQueryClient();

  const list = useQuery({ queryKey: ["mindmaps"], queryFn: mindmapApi.list, enabled: !map });
  const generate = useMutation({
    mutationFn: () => mindmapApi.generate(Array.from(selectedDocs)),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["mindmaps"] });
      setMap(data);
    },
    onError: () => setError("Mind map generation failed."),
  });

  if (map) return <MindMapExplorer map={map} onExit={() => setMap(null)} />;

  return (
    <group>
      <ScreenHeader title="Mind map" subtitle="Open a saved map or generate one from your selected documents" />
      {generate.isPending ? (
        <Busy text="Mapping your documents… this can take a minute" />
      ) : (
        <SavedList
          items={(list.data ?? []).map((m) => ({
            id: m.mind_map_id,
            title: m.mind_map.nodes[0]?.content ?? "Mind map",
            subtitle: `${m.node_count} nodes · ${m.document_count} docs`,
          }))}
          loading={list.isLoading}
          onOpen={(id) => {
            const found = list.data?.find((m) => m.mind_map_id === id);
            if (found) setMap(found);
          }}
          onGenerate={() => {
            setError(null);
            generate.mutate();
          }}
          generateLabel="Generate mind map"
          canGenerate={selectedDocs.size > 0}
          emptyText="No mind maps yet."
          error={error}
        />
      )}
    </group>
  );
}

const CHILD_ROWS = 6;

function MindMapExplorer({ map, onExit }: { map: MindMapResponse; onExit: () => void }) {
  const showToast = useXRUi((s) => s.showToast);
  const { nodes, children, parent, rootId } = useMemo(() => {
    const nodes = new Map(map.mind_map.nodes.map((n) => [n.id, n.content]));
    const children = new Map<string, string[]>();
    const parent = new Map<string, string>();
    for (const e of map.mind_map.edges) {
      if (!nodes.has(e.from_id) || !nodes.has(e.to_id) || parent.has(e.to_id)) continue;
      children.set(e.from_id, [...(children.get(e.from_id) ?? []), e.to_id]);
      parent.set(e.to_id, e.from_id);
    }
    const rootId = map.mind_map.nodes.find((n) => !parent.has(n.id))?.id ?? map.mind_map.nodes[0]?.id;
    return { nodes, children, parent, rootId };
  }, [map]);

  const [focus, setFocus] = useState(rootId);
  const kids = (focus && children.get(focus)) || [];
  const pages = Math.max(1, Math.ceil(kids.length / CHILD_ROWS));
  const pager = usePager(pages, focus);
  const shown = kids.slice(pager.page * CHILD_ROWS, pager.page * CHILD_ROWS + CHILD_ROWS);

  const drill = (id: string) => {
    if ((children.get(id) ?? []).length === 0) {
      showToast("End of this branch");
      return false;
    }
    setFocus(id);
    return true;
  };
  const up = () => {
    const p = focus ? parent.get(focus) : undefined;
    if (!p) return false;
    setFocus(p);
    return true;
  };

  useScreenHandlers({
    next: pager.next,
    prev: pager.prev,
    choose: (n) => (shown[n - 1] ? drill(shown[n - 1]) : false),
    back: () => up() || (onExit(), true),
  });

  // Breadcrumb from root to focus.
  const trail: string[] = [];
  for (let id: string | undefined = focus; id; id = parent.get(id)) trail.unshift(nodes.get(id) ?? "");

  const focusX = -0.25;
  const childX = 0.2;
  const rowH = 0.072;
  const top = ((shown.length - 1) * rowH) / 2 - 0.04;

  return (
    <group>
      <ScreenHeader title="Mind map" subtitle={trail.join("  >  ")} onBack={onExit} backLabel="All maps" />
      <Panel width={0.36} height={0.14} position={[focusX, -0.04, 0.004]}>
        <T fontSize={0.022} maxWidth={0.32} textAlign="center">
          {focus ? nodes.get(focus) : ""}
        </T>
      </Panel>
      {shown.map((id, i) => {
        const y = top - i * rowH;
        const hasKids = (children.get(id) ?? []).length > 0;
        return (
          <group key={id}>
            <Line points={[[focusX + 0.18, -0.04, 0.01], [childX - 0.2, y, 0.01]]} color={C.border} lineWidth={1.5} />
            <Button
              label={hasKids ? `${nodes.get(id)}  +` : nodes.get(id) ?? ""}
              width={0.4}
              height={0.06}
              fontSize={0.015}
              align="left"
              color={hasKids ? "#17324f" : C.button}
              position={[childX, y, 0]}
              onClick={() => drill(id)}
            />
          </group>
        );
      })}
      {kids.length === 0 && (
        <T position={[childX, -0.04, 0]} fontSize={0.016} color={C.muted}>
          No sub-topics
        </T>
      )}
      <Button label="Up a level" width={0.16} disabled={!focus || !parent.get(focus)} position={[-SCREEN_W / 2 + 0.12, -SCREEN_H / 2 + 0.04, 0]} onClick={up} />
      {pages > 1 && (
        <T position={[childX, -SCREEN_H / 2 + 0.04, 0]} fontSize={0.014} color={C.muted}>
          {`${pager.page + 1} / ${pages} · swipe for more`}
        </T>
      )}
    </group>
  );
}
