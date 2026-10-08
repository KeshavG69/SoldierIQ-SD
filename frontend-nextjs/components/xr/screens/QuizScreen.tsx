"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Busy, Button, C, SCREEN_H, SCREEN_W, SavedList, ScreenHeader, T, fmtDate, useScreenHandlers } from "../ui";
import { quizApi, type QuizData } from "@/lib/api/quiz";
import { useDocumentStore } from "@/lib/stores/documentStore";
import { useXRUi } from "@/lib/stores/xrUiStore";

const LETTERS = ["A", "B", "C", "D"] as const;

export default function QuizScreen() {
  const [quiz, setQuiz] = useState<QuizData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedDocs = useDocumentStore((s) => s.selectedDocs);
  const queryClient = useQueryClient();

  const list = useQuery({ queryKey: ["quizzes"], queryFn: quizApi.list, enabled: !quiz });

  const open = useMutation({
    mutationFn: quizApi.getById,
    onSuccess: setQuiz,
    onError: () => setError("Could not load that quiz."),
  });
  const generate = useMutation({
    mutationFn: () =>
      quizApi.generate(Array.from(selectedDocs), { question_count: "standard", difficulty: "medium" }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["quizzes"] });
      setQuiz(data);
    },
    onError: () => setError("Quiz generation failed."),
  });

  if (quiz) return <QuizPlayer quiz={quiz} onExit={() => setQuiz(null)} />;

  return (
    <group>
      <ScreenHeader title="Quiz" subtitle="Open a saved quiz or generate one from your selected documents" />
      {generate.isPending || open.isPending ? (
        <Busy text={generate.isPending ? "Writing your quiz… this can take a minute" : "Loading quiz…"} />
      ) : (
        <SavedList
          items={(list.data ?? []).map((q) => ({
            id: q.workflow_id,
            title: q.title,
            subtitle: `${q.question_count} questions · ${fmtDate(q.created_at)}`,
          }))}
          loading={list.isLoading}
          onOpen={(id) => {
            setError(null);
            open.mutate(id);
          }}
          onGenerate={() => {
            setError(null);
            generate.mutate();
          }}
          generateLabel="Generate quiz"
          canGenerate={selectedDocs.size > 0}
          emptyText="No saved quizzes yet."
          error={error}
        />
      )}
    </group>
  );
}

function QuizPlayer({ quiz, onExit }: { quiz: QuizData; onExit: () => void }) {
  const [index, setIndex] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [score, setScore] = useState(0);
  const [showHint, setShowHint] = useState(false);
  const [done, setDone] = useState(false);
  const showToast = useXRUi((s) => s.showToast);

  const total = quiz.questions.length;
  const q = quiz.questions[index];
  const options = q?.options.slice(0, 4) ?? [];

  const pick = (i: number) => {
    if (submitted || i >= options.length) return false;
    setPicked(i);
    return true;
  };
  const submit = () => {
    if (submitted || picked === null) return false;
    setSubmitted(true);
    const correct = options[picked]?.is_correct;
    if (correct) setScore((s) => s + 1);
    showToast(correct ? "Correct!" : "Not quite");
    return true;
  };
  const next = () => {
    if (!submitted) return false;
    if (index + 1 >= total) setDone(true);
    else {
      setIndex(index + 1);
      setPicked(null);
      setSubmitted(false);
      setShowHint(false);
    }
    return true;
  };
  const restart = () => {
    setIndex(0);
    setPicked(null);
    setSubmitted(false);
    setScore(0);
    setShowHint(false);
    setDone(false);
  };

  useScreenHandlers({
    choose: (n) => pick(n - 1),
    confirm: () => (submitted ? next() : submit()),
    next,
    back: () => {
      onExit();
      return true;
    },
  });

  if (done || !q) {
    return (
      <group>
        <ScreenHeader title={quiz.title} subtitle="Quiz complete" onBack={onExit} backLabel="All quizzes" />
        <T position={[0, 0.05, 0]} fontSize={0.07}>
          {`${score} / ${total}`}
        </T>
        <T position={[0, -0.03, 0]} fontSize={0.02} color={C.muted}>
          {score === total ? "Perfect score." : `${Math.round((score / Math.max(1, total)) * 100)}% correct`}
        </T>
        <Button label="Try again" width={0.18} color={C.accent} position={[-0.11, -0.13, 0]} onClick={restart} />
        <Button label="All quizzes" width={0.18} position={[0.11, -0.13, 0]} onClick={onExit} />
      </group>
    );
  }

  const chosen = picked !== null ? options[picked] : null;
  return (
    <group>
      <ScreenHeader title={quiz.title} subtitle={`Question ${index + 1} of ${total} · score ${score}`} onBack={onExit} backLabel="All quizzes" />
      <T position={[-SCREEN_W / 2 + 0.04, 0.2, 0]} anchorX="left" fontSize={0.024} maxWidth={SCREEN_W - 0.08}>
        {q.question}
      </T>
      {options.map((opt, i) => {
        let color = C.button;
        if (submitted && opt.is_correct) color = "#1d5a43";
        else if (submitted && i === picked) color = "#6b2427";
        else if (i === picked) color = "#17324f";
        return (
          <Button
            key={i}
            label={`${LETTERS[i]}.  ${opt.text}`}
            width={SCREEN_W - 0.08}
            height={0.074}
            align="left"
            fontSize={0.017}
            color={color}
            position={[0, 0.085 - i * 0.084, 0]}
            onClick={() => pick(i)}
          />
        );
      })}
      <T
        position={[-SCREEN_W / 2 + 0.04, -0.265, 0]}
        anchorX="left"
        fontSize={0.014}
        color={submitted ? (chosen?.is_correct ? C.success : C.danger) : C.muted}
        maxWidth={0.55}
      >
        {submitted
          ? chosen?.rationale ?? ""
          : showHint
            ? `Hint: ${q.hint}`
            : "Hold up 1-4 fingers or pinch an answer, then thumbs up to submit."}
      </T>
      {!submitted && (
        <Button label="Hint" width={0.1} position={[0.17, -0.27, 0]} onClick={() => setShowHint(true)} />
      )}
      <Button
        label={submitted ? (index + 1 >= total ? "Finish" : "Next") : "Submit"}
        width={0.14}
        color={C.accent}
        disabled={!submitted && picked === null}
        position={[SCREEN_W / 2 - 0.1, -SCREEN_H / 2 + 0.07, 0]}
        onClick={() => (submitted ? next() : submit())}
      />
    </group>
  );
}
