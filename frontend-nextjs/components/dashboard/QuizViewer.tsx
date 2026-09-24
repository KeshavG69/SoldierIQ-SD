"use client";

import { useState, useEffect } from "react";
import { QuizData } from "@/lib/api/quiz";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

interface QuizViewerProps {
  quizData: QuizData;
  onClose: () => void;
}

const LETTERS = ["A", "B", "C", "D", "E", "F"];

export default function QuizViewer({ quizData, onClose }: QuizViewerProps) {
  const { title, questions } = quizData;
  const totalQuestions = questions.length;
  const sourceCount = quizData.document_count || 0;
  const difficulty = quizData.settings?.difficulty;

  const [currentIndex, setCurrentIndex] = useState(0);
  // Selected option index per question; null = unanswered
  const [answers, setAnswers] = useState<(number | null)[]>(() => questions.map(() => null));
  const [hintShown, setHintShown] = useState<boolean[]>(() => questions.map(() => false));
  const [showResults, setShowResults] = useState(false);

  const currentQuestion = questions[currentIndex];
  const selected = answers[currentIndex];
  const isAnswered = selected !== null;

  const answeredCount = answers.filter((a) => a !== null).length;
  const score = answers.filter((a, i) => a !== null && questions[i].options[a]?.is_correct).length;
  const isLast = currentIndex === totalQuestions - 1;
  const percent = totalQuestions ? Math.round((score / totalQuestions) * 100) : 0;

  const selectOption = (optionIndex: number) => {
    if (isAnswered || optionIndex >= currentQuestion.options.length) return;
    setAnswers((prev) => prev.map((a, i) => (i === currentIndex ? optionIndex : a)));
  };

  const showHint = () => {
    setHintShown((prev) => prev.map((h, i) => (i === currentIndex ? true : h)));
  };

  const goTo = (index: number) => {
    if (index >= 0 && index < totalQuestions) setCurrentIndex(index);
  };

  const handleNext = () => {
    if (isLast) {
      setShowResults(true);
    } else {
      goTo(currentIndex + 1);
    }
  };

  const handleRetake = () => {
    setAnswers(questions.map(() => null));
    setHintShown(questions.map(() => false));
    setCurrentIndex(0);
    setShowResults(false);
  };

  const handleReview = (index: number) => {
    setShowResults(false);
    setCurrentIndex(index);
  };

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (showResults) return;

      const letterIndex = LETTERS.indexOf(e.key.toUpperCase());
      const numberIndex = parseInt(e.key, 10) - 1;
      if (letterIndex !== -1) {
        selectOption(letterIndex);
      } else if (numberIndex >= 0 && numberIndex < LETTERS.length) {
        selectOption(numberIndex);
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        goTo(currentIndex - 1);
      } else if (e.key === "ArrowRight" || e.key === "Enter") {
        e.preventDefault();
        if (isAnswered) handleNext();
      }
    };

    // Capture phase: the Dialog stops propagation of arrow keys before they bubble to window
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [currentIndex, isAnswered, showResults, answers]);

  const optionClass = (optionIndex: number) => {
    const option = currentQuestion.options[optionIndex];
    if (!isAnswered) {
      return "border-border bg-card hover:border-brand/50 hover:bg-surface-2 dark:hover:bg-accent/60 cursor-pointer";
    }
    if (option.is_correct) {
      return "border-emerald-500/70 bg-emerald-50 dark:bg-emerald-950/30";
    }
    if (optionIndex === selected) {
      return "border-red-500/70 bg-red-50 dark:bg-red-950/30";
    }
    return "border-border bg-card opacity-70";
  };

  return (
    <Dialog open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-2xl p-0 gap-0 flex flex-col max-h-[85vh] overflow-hidden">
        {/* Header */}
        <div className="border-b border-border px-5 py-4 pr-12">
          <DialogTitle className="text-base font-semibold text-foreground truncate">{title}</DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground mt-0.5">
            Based on {sourceCount} {sourceCount === 1 ? "source" : "sources"}
            {difficulty && <span className="capitalize"> · {difficulty}</span>}
          </DialogDescription>
        </div>

        <div className="flex-1 overflow-y-auto tactical-scrollbar">
          <div className="px-5 py-5">
            {showResults ? (
              /* Results */
              <div>
                <div className="rounded-xl border border-border bg-card p-5 text-center mb-5">
                  <p className="text-sm text-muted-foreground mb-1">Your score</p>
                  <p className="text-3xl font-bold text-foreground">
                    {score} <span className="text-muted-foreground text-2xl font-medium">/ {totalQuestions}</span>
                  </p>
                  <p className="text-sm text-muted-foreground mt-1">
                    {percent}% correct
                    {answeredCount < totalQuestions && ` · ${totalQuestions - answeredCount} unanswered`}
                  </p>
                  <div className="mt-5 flex justify-center gap-2">
                    <button
                      onClick={handleRetake}
                      className="px-4 py-2 rounded-lg bg-brand text-brand-foreground text-sm font-medium hover:bg-brand/90 transition-colors"
                    >
                      Retake quiz
                    </button>
                    <button
                      onClick={onClose}
                      className="px-4 py-2 rounded-lg border border-border text-sm font-medium text-foreground hover:bg-secondary transition-colors"
                    >
                      Done
                    </button>
                  </div>
                </div>

                <h2 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground mb-2">Review</h2>
                <div className="flex flex-col gap-2">
                  {questions.map((q, i) => {
                    const answer = answers[i];
                    const correct = answer !== null && q.options[answer]?.is_correct;
                    return (
                      <button
                        key={i}
                        onClick={() => handleReview(i)}
                        className="flex items-start gap-3 rounded-lg border border-border bg-card p-3 text-left hover:bg-surface-2 dark:hover:bg-accent/60 transition-colors"
                      >
                        <span
                          className={`mt-0.5 w-5 h-5 shrink-0 rounded-full flex items-center justify-center text-[11px] font-bold text-white ${
                            answer === null ? "bg-muted-foreground/50" : correct ? "bg-emerald-500" : "bg-red-500"
                          }`}
                        >
                          {answer === null ? "–" : correct ? "✓" : "✕"}
                        </span>
                        <span className="text-sm text-foreground leading-snug">
                          <span className="text-muted-foreground mr-1">{i + 1}.</span>
                          {q.question}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : (
              /* Question */
              <div>
                <div className="flex items-center justify-between mb-2 text-xs text-muted-foreground">
                  <span>
                    Question {currentIndex + 1} of {totalQuestions}
                  </span>
                  <span>
                    Score {score} / {answeredCount}
                  </span>
                </div>
                <div className="h-1 bg-secondary rounded-full overflow-hidden mb-5">
                  <div
                    className="h-full bg-brand transition-all duration-300"
                    style={{ width: `${(answeredCount / totalQuestions) * 100}%` }}
                  />
                </div>

                <h2 className="text-base font-semibold text-foreground leading-relaxed mb-4">
                  {currentQuestion.question}
                </h2>

                <div className="flex flex-col gap-2">
                  {currentQuestion.options.map((option, i) => {
                    const showRationale = isAnswered && (option.is_correct || i === selected);
                    return (
                      <button
                        key={i}
                        onClick={() => selectOption(i)}
                        disabled={isAnswered}
                        className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors disabled:cursor-default ${optionClass(i)}`}
                      >
                        <div className="flex items-start gap-3">
                          <span className="mt-px w-6 h-6 shrink-0 rounded-md border border-border bg-secondary flex items-center justify-center text-xs font-semibold text-muted-foreground">
                            {LETTERS[i]}
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="text-sm text-foreground leading-relaxed">{option.text}</p>
                            {showRationale && (
                              <p
                                className={`mt-2 text-xs leading-relaxed ${
                                  option.is_correct
                                    ? "text-emerald-700 dark:text-emerald-400"
                                    : "text-red-700 dark:text-red-400"
                                }`}
                              >
                                <span className="font-semibold">
                                  {option.is_correct ? "Right answer. " : "Not quite. "}
                                </span>
                                {option.rationale}
                              </p>
                            )}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>

                {/* Hint (before answering) / source evidence (after answering) */}
                <div className="mt-3 min-h-[2rem]">
                  {!isAnswered &&
                    currentQuestion.hint &&
                    (hintShown[currentIndex] ? (
                      <div className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-muted-foreground">
                        <span className="font-medium text-foreground">Hint: </span>
                        {currentQuestion.hint}
                      </div>
                    ) : (
                      <button onClick={showHint} className="text-sm text-brand hover:underline">
                        Show hint
                      </button>
                    ))}
                  {isAnswered && (currentQuestion.evidence || currentQuestion.source) && (
                    <div className="rounded-lg border-l-2 border-brand/60 bg-card px-3 py-2">
                      {currentQuestion.evidence && (
                        <p className="text-sm italic text-muted-foreground leading-relaxed">
                          &ldquo;{currentQuestion.evidence}&rdquo;
                        </p>
                      )}
                      {currentQuestion.source && (
                        <p className="text-xs text-muted-foreground mt-1">Source: {currentQuestion.source}</p>
                      )}
                    </div>
                  )}
                </div>

                {/* Navigation */}
                <div className="mt-5 flex items-center justify-between">
                  <button
                    onClick={() => goTo(currentIndex - 1)}
                    disabled={currentIndex === 0}
                    className="px-4 py-2 rounded-lg border border-border text-sm font-medium text-foreground hover:bg-secondary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    Previous
                  </button>
                  <p className="hidden sm:block text-xs text-muted-foreground">
                    <kbd className="px-1.5 py-0.5 bg-secondary border border-border rounded text-[10px]">A–D</kbd> answer
                    <kbd className="ml-2 px-1.5 py-0.5 bg-secondary border border-border rounded text-[10px]">← / →</kbd> navigate
                  </p>
                  <button
                    onClick={handleNext}
                    disabled={!isAnswered && !isLast}
                    className="px-4 py-2 rounded-lg bg-brand text-brand-foreground text-sm font-medium hover:bg-brand/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    {isLast ? "See results" : "Next"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
