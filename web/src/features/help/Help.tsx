import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { copy, helpAnswers, glyphs, label } from "../../copy";
import { Button } from "../../shared/Button";
import { Icon } from "../../shared/Icon";
import { usePreferences, useSession } from "../../shared/state";
import registry from "../../registry.json";
export function Help() {
  const session = useSession();
  const node = registry.nodes.find((n) => n.id === session.panel);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (session.help !== null) input.current?.focus();
  }, [session.help]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && session.help !== null) {
        e.stopImmediatePropagation();
        session.set({ help: null });
      }
    };
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, [session]);
  const questions = copy.questions
    .map((question, i) => ({ question, i }))
    .filter((v) => v.question.toLowerCase().includes(search.toLowerCase()));
  useEffect(() => {
    if (
      session.help !== null &&
      session.help >= 0 &&
      !questions
        .slice(page * 4, page * 4 + 4)
        .some((item) => item.i === session.help)
    ) {
      setSearch("");
      setPage(Math.floor(session.help / 4));
    }
  }, [session.help]);
  return (
    <AnimatePresence>
      {session.help !== null && (
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-label={copy.help}
          className="help-drawer"
          initial={{ x: "100%" }}
          animate={{ x: 0 }}
          exit={{ x: "100%" }}
          transition={{ type: "spring", damping: 30, stiffness: 300 }}
          data-testid="help-view"
        >
          <div className="help-controls">
            <Icon name="search" />
            <input
              ref={input}
              aria-label={copy.searchHelp}
              placeholder={copy.searchHelp}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(0);
              }}
            />
            <Button
              icon="close"
              title={copy.close}
              onClick={() => session.set({ help: null })}
            />
          </div>
          {node && (
            <div className="help-answer" data-help-answer="true">
              <strong>{label(node.label_key)}</strong>
              <p>{node.io.takes.noun + " → " + node.io.gives.noun}</p>
              <p>{node.io.takes.plain_line}</p>
              <p>{node.io.gives.plain_line}</p>
              <a href="/io.md" target="_blank" rel="noreferrer">
                {copy.docs}
              </a>
            </div>
          )}
          <div className="questions">
            {questions.slice(page * 4, page * 4 + 4).map(({ question, i }) => (
              <div key={question}>
                <button
                  aria-expanded={session.help === i}
                  onClick={() =>
                    session.set({ help: session.help === i ? -1 : i })
                  }
                >
                  <Icon
                    name={
                      [
                        "model",
                        "lens",
                        "members",
                        "question",
                        "gate",
                        "review",
                        "plan",
                        "run",
                        "resume",
                        "privacy",
                        "model",
                        "limiter",
                        "check",
                        "plus",
                      ][i]
                    }
                  />
                  {question}
                  <span>{session.help === i ? glyphs.minus : glyphs.plus}</span>
                </button>
                {session.help === i && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    className="help-answer"
                    data-help-answer="true"
                  >
                    {helpAnswers[i]}
                  </motion.div>
                )}
              </div>
            ))}
          </div>
          <div className="pager">
            <Button
              icon="previous"
              title={copy.previous}
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
            />
            <span>
              {page + 1}/{Math.max(1, Math.ceil(questions.length / 4))}
            </span>
            <Button
              icon="next"
              title={copy.next}
              disabled={(page + 1) * 4 >= questions.length}
              onClick={() => setPage(page + 1)}
            />
            <Button
              icon="flask"
              title={copy.tour}
              onClick={() => {
                usePreferences.getState().set({ tourDone: false });
                session.set({ help: null });
              }}
            />
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
export function Tour() {
  const preferences = usePreferences();
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (preferences.tourDone) return;
    const target = document.querySelector<HTMLElement>(
      [
        ".toolbar > button",
        ".workflow-node.wide",
        ".drawer-toggle",
        ".toolbar > button:last-child",
      ][step],
    );
    target?.classList.add("tour-spotlight");
    return () => target?.classList.remove("tour-spotlight");
  }, [step, preferences.tourDone]);
  return (
    <AnimatePresence>
      {!preferences.tourDone && (
        <motion.div
          className={`tour tour-${step}`}
          role="dialog"
          aria-label={copy.tour}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <span>{`${step + 1}/${copy.tourLabels.length}`}</span>
          <Icon name={["run", "flask", "lens", "help"][step]} />
          <span>{copy.tourLabels[step]}</span>
          <Button
            icon="next"
            title={copy.next}
            onClick={() => {
              if (step === 3) {
                preferences.set({ tourDone: true });
                setStep(0);
              } else setStep(step + 1);
            }}
          />
          <Button
            icon="close"
            title={copy.close}
            onClick={() => preferences.set({ tourDone: true })}
          />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
