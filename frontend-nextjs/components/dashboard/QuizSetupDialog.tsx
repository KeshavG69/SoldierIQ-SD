"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { quizApi, QuizDifficulty, QuizOptions, QuizQuestionCount } from "@/lib/api/quiz";

interface QuizSetupDialogProps {
  open: boolean;
  documentCount: number;
  onClose: () => void;
  onGenerate: (options: QuizOptions) => void;
  onOpenQuiz: (workflowId: string) => void;
}

const COUNT_OPTIONS: { value: QuizQuestionCount; label: string; hint: string }[] = [
  { value: "fewer", label: "Fewer", hint: "5" },
  { value: "standard", label: "Standard", hint: "10" },
  { value: "more", label: "More", hint: "20" },
];

const DIFFICULTY_OPTIONS: { value: QuizDifficulty; label: string }[] = [
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
];

function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string; hint?: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="grid grid-cols-3 gap-1 rounded-lg bg-secondary p-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          aria-pressed={value === option.value}
          className={`rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
            value === option.value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {option.label}
          {option.hint && <span className="ml-1 text-muted-foreground">({option.hint})</span>}
        </button>
      ))}
    </div>
  );
}

function formatDate(iso: string | null) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export default function QuizSetupDialog({
  open,
  documentCount,
  onClose,
  onGenerate,
  onOpenQuiz,
}: QuizSetupDialogProps) {
  const [questionCount, setQuestionCount] = useState<QuizQuestionCount>("standard");
  const [difficulty, setDifficulty] = useState<QuizDifficulty>("medium");
  const [topic, setTopic] = useState("");

  const { data: savedQuizzes, isLoading: isLoadingSaved } = useQuery({
    queryKey: ["quizzes"],
    queryFn: quizApi.list,
    enabled: open,
  });

  const handleGenerate = () => {
    onGenerate({
      question_count: questionCount,
      difficulty,
      topic: topic.trim() || undefined,
    });
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Quiz</DialogTitle>
          <DialogDescription>
            {documentCount > 0
              ? `Multiple-choice questions from ${documentCount} selected ${documentCount === 1 ? "source" : "sources"}.`
              : "Select documents to generate a new quiz, or reopen a saved one."}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-foreground">Number of questions</label>
            <Segmented options={COUNT_OPTIONS} value={questionCount} onChange={setQuestionCount} />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-foreground">Difficulty</label>
            <Segmented options={DIFFICULTY_OPTIONS} value={difficulty} onChange={setDifficulty} />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="quiz-topic" className="text-xs font-medium text-foreground">
              What should the quiz focus on? <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <textarea
              id="quiz-topic"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              maxLength={500}
              rows={2}
              placeholder="e.g. Only cover the maintenance procedures in chapter 3"
              className="w-full resize-none rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm text-foreground placeholder:text-muted-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleGenerate} disabled={documentCount === 0}>
            Generate
          </Button>
        </DialogFooter>

        {/* Saved quizzes */}
        <div className="border-t border-border pt-3">
          <h3 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground mb-2">
            Recent quizzes
          </h3>
          {isLoadingSaved ? (
            <p className="text-xs text-muted-foreground">Loading…</p>
          ) : !savedQuizzes || savedQuizzes.length === 0 ? (
            <p className="text-xs text-muted-foreground">No saved quizzes yet.</p>
          ) : (
            <div className="flex max-h-48 flex-col gap-1 overflow-y-auto tactical-scrollbar -mx-1 px-1">
              {savedQuizzes.map((quiz) => (
                <button
                  key={quiz.workflow_id}
                  type="button"
                  onClick={() => onOpenQuiz(quiz.workflow_id)}
                  className="rounded-lg px-2 py-1.5 text-left hover:bg-secondary transition-colors"
                >
                  <div className="text-sm text-foreground truncate">{quiz.title}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {quiz.question_count} questions
                    {quiz.settings?.difficulty && <span className="capitalize"> · {quiz.settings.difficulty}</span>}
                    {quiz.created_at && ` · ${formatDate(quiz.created_at)}`}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
