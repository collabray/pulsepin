import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client.js";

export default function Triage() {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    api
      .startTriage({})
      .then(setSession)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function answer(value) {
    if (!session?.next_question_symptom) return;
    setLoading(true);
    try {
      const updated = await api.answerTriage(session.session_id, session.next_question_symptom, value);
      setSession(updated);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  if (loading && !session) {
    return (
      <div className="screen" style={{ justifyContent: "center" }}>
        <p className="dim">Starting triage…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="screen">
        <div className="error-text">{error}</div>
      </div>
    );
  }

  const isComplete = session?.is_complete;

  return (
    <div className="screen">
      <h1>Symptom check</h1>
      <p className="subtitle">Answer a few quick yes/no questions.</p>

      {session?.urgency_level && (
        <div className="card">
          <span className={`badge ${session.urgency_level}`}>{session.urgency_level.replace("_", " ")}</span>
          <h2 style={{ marginTop: 10 }}>
            {session.top_condition ? session.top_condition : "Assessing…"}
          </h2>
          <p className="dim">
            {session.top_probability != null &&
              `Model confidence: ${(session.top_probability * 100).toFixed(0)}%`}
          </p>
          {session.urgency_level === "uncertain" && (
            <p className="dim">
              We couldn't reach a confident conclusion from symptoms alone. Please see a doctor for a
              proper diagnosis — this is exactly the kind of case a symptom checker shouldn't guess on.
            </p>
          )}
        </div>
      )}

      {!isComplete && session?.next_question_label && (
        <div className="card">
          <h2>{session.next_question_label}</h2>
          <div className="question-row">
            <button className="ghost" onClick={() => answer(0)} disabled={loading}>
              No
            </button>
            <button className="primary" onClick={() => answer(1)} disabled={loading}>
              Yes
            </button>
          </div>
        </div>
      )}

      {isComplete && (
        <div className="card">
          <h2>Top possibilities</h2>
          {session.ranked_conditions.slice(0, 3).map((c) => (
            <div key={c.condition} className="facility-row">
              <span>{c.condition}</span>
              <span className="dim">{(c.probability * 100).toFixed(0)}%</span>
            </div>
          ))}
          <button
            className="primary"
            style={{ marginTop: 16 }}
            onClick={() =>
              navigate("/hospitals", { state: { condition: session.top_condition, urgency: session.urgency_level } })
            }
          >
            Find nearby care
          </button>
        </div>
      )}

      <p className="dim" style={{ marginTop: "auto" }}>
        This tool does not replace a doctor. If you're in immediate danger, seek emergency care now.
      </p>
    </div>
  );
}
