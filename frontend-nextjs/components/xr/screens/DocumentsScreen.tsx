"use client";

import { useMemo } from "react";

import { Button, Busy, C, SCREEN_H, SCREEN_W, ScreenHeader, T, usePager, useScreenHandlers } from "../ui";
import { useAuthStore } from "@/lib/stores/authStore";
import { useDocumentStore } from "@/lib/stores/documentStore";
import { useDocuments } from "@/lib/hooks/useDocuments";

const ROWS = 6;

export default function DocumentsScreen() {
  const user = useAuthStore((s) => s.user);
  const { data: documents = [], isLoading } = useDocuments(user?.organization_id);
  const selectedDocs = useDocumentStore((s) => s.selectedDocs);
  const toggle = useDocumentStore((s) => s.toggleDocSelection);
  const selectDocs = useDocumentStore((s) => s.selectDocs);
  const deselectDocs = useDocumentStore((s) => s.deselectDocs);

  const ready = useMemo(() => documents.filter((d) => d.status !== "failed"), [documents]);
  const pages = Math.max(1, Math.ceil(ready.length / ROWS));
  const pager = usePager(pages, ready.length);
  const rows = ready.slice(pager.page * ROWS, pager.page * ROWS + ROWS);

  useScreenHandlers({
    next: pager.next,
    prev: pager.prev,
    choose: (n) => {
      const doc = rows[n - 1];
      if (!doc) return false;
      toggle(doc.id);
      return true;
    },
  });

  const top = SCREEN_H / 2 - 0.15;
  return (
    <group>
      <ScreenHeader title="Documents" subtitle={`${selectedDocs.size} selected · pinch a row to toggle`} />
      <Button label="Select all" width={0.16} position={[-SCREEN_W / 2 + 0.12, top, 0]} onClick={() => selectDocs(ready.map((d) => d.id))} />
      <Button label="Clear" width={0.12} position={[-SCREEN_W / 2 + 0.28, top, 0]} onClick={() => deselectDocs(Array.from(selectedDocs))} />
      {isLoading ? (
        <Busy text="Loading documents…" y={-0.05} />
      ) : ready.length === 0 ? (
        <T position={[0, -0.05, 0]} fontSize={0.02} color={C.muted}>
          No documents yet - upload some on the dashboard.
        </T>
      ) : (
        rows.map((doc, i) => {
          const on = selectedDocs.has(doc.id);
          const y = top - 0.085 - i * 0.062;
          return (
            <group key={doc.id} position={[0, y, 0]}>
              <mesh position={[-SCREEN_W / 2 + 0.05, 0, 0.008]}>
                <planeGeometry args={[0.026, 0.026]} />
                <meshBasicMaterial color={on ? C.success : "#2a2f36"} />
              </mesh>
              <Button
                label={doc.folder_name ? `${doc.file_name}   ·   ${doc.folder_name}` : doc.file_name}
                width={SCREEN_W - 0.14}
                height={0.05}
                align="left"
                color={on ? "#17324f" : C.button}
                position={[0.035, 0, 0]}
                onClick={() => toggle(doc.id)}
              />
              {doc.status === "processing" && (
                <T position={[SCREEN_W / 2 - 0.1, 0, 0.012]} fontSize={0.013} color={C.warning}>
                  processing
                </T>
              )}
            </group>
          );
        })
      )}
      {pages > 1 && (
        <T position={[0, -SCREEN_H / 2 + 0.035, 0]} fontSize={0.014} color={C.muted}>
          {`Page ${pager.page + 1} / ${pages} · swipe to change page`}
        </T>
      )}
    </group>
  );
}
