import { useState, type SyntheticEvent } from "react";

import { useAuth } from "../auth";
import { Actions, Card, Field, FormError } from "../components/ui";
import styles from "./Page.module.css";

export function LoginPage() {
  const { login } = useAuth();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: SyntheticEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(name, password);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.login}>
      <Card>
        <h1>ColdKeeper</h1>
        <p className={styles.muted}>Мониторинг температуры холодильного оборудования</p>
        <form onSubmit={(event) => void submit(event)} className={styles.stack}>
          <Field label="Логин">
            {(id) => (
              <input
                id={id}
                autoComplete="username"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            )}
          </Field>
          <Field label="Пароль">
            {(id) => (
              <input
                id={id}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            )}
          </Field>
          <FormError error={error} />
          <Actions>
            <button type="submit" disabled={busy}>
              {busy ? "Входим…" : "Войти"}
            </button>
          </Actions>
        </form>
      </Card>
    </div>
  );
}
