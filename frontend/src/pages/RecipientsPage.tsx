import { useState } from "react";

import { recipientActions, useChange, useRecipients } from "../api/queries";
import type { BindingCode } from "../api/types";
import { useAuth } from "../auth";
import { Actions, Card, Dialog, Empty, ErrorState, FormError, Loading, Secret, TableWrap } from "../components/ui";
import styles from "./Page.module.css";

export function RecipientsPage() {
  const recipients = useRecipients();
  const { isOwner, session } = useAuth();
  const [code, setCode] = useState<BindingCode | null>(null);
  const createCode = useChange(recipientActions.code, []);
  const setActive = useChange(recipientActions.setActive, [["recipients"]]);

  if (recipients.isPending) return <Loading what="получателей" />;
  if (recipients.isError) return <ErrorState error={recipients.error} retry={() => void recipients.refetch()} />;
  const { bot_configured: botConfigured, bot_username: botUsername } = recipients.data;

  return (
    <div className={styles.stack}>
      <div className={styles.head}>
        <h1>Уведомления в Telegram</h1>
        {isOwner && (
          <button
            type="button"
            disabled={!botConfigured}
            title={botConfigured ? undefined : "Сначала подключите бота на сервере"}
            onClick={() => createCode.mutate(undefined, { onSuccess: setCode })}
          >
            Получить код привязки
          </button>
        )}
      </div>
      <Card>
        {botConfigured && session?.public_demo ? (
          <p>
            Откройте <a href={`https://t.me/${botUsername}`}>@{botUsername}</a> и нажмите «Старт». Бот пришлёт
            сообщение, когда в демо-кафе «Север» откроется или закроется инцидент.
          </p>
        ) : botConfigured ? (
          <p>
            Бот <strong>@{botUsername}</strong> подключён. Уведомления приходят при открытии инцидента и при
            восстановлении, а не на каждое измерение.
          </p>
        ) : (
          <p>
            <strong>Бот не подключён.</strong> Уведомления формируются и видны в разделе «Инциденты», но в Telegram не
            отправляются (режим dry-run). Для отправки задайте токен и имя бота на сервере (см. README).
          </p>
        )}
      </Card>
      <FormError error={createCode.error ?? setActive.error} />
      {recipients.data.recipients.length === 0 ? (
        <Empty>Получателей пока нет.</Empty>
      ) : (
        <TableWrap label="Получатели">
          <table>
            <thead>
              <tr>
                <th>Чат</th>
                <th>Привязан</th>
                <th>Состояние</th>
                {isOwner && <th>Действия</th>}
              </tr>
            </thead>
            <tbody>
              {recipients.data.recipients.map((recipient) => (
                <tr key={recipient.id}>
                  <td>{recipient.title}</td>
                  <td>{new Date(recipient.created_at).toLocaleString("ru-RU")}</td>
                  <td>{recipient.is_active ? "получает уведомления" : "на паузе"}</td>
                  {isOwner && (
                    <td>
                      <button
                        type="button"
                        className="link"
                        onClick={() => setActive.mutate({ id: recipient.id, active: !recipient.is_active })}
                      >
                        {recipient.is_active ? "Приостановить" : "Возобновить"}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      <Dialog title="Код привязки чата" open={code !== null} onClose={() => setCode(null)}>
        {code && (
          <>
            <p>Код действует 15 минут и подходит один раз.</p>
            <Secret>{code.code}</Secret>
            {code.deep_link ? (
              <p>
                Откройте ссылку в Telegram на телефоне получателя: <a href={code.deep_link}>{code.deep_link}</a>
              </p>
            ) : (
              <p className={styles.muted}>
                Бот не подключён: код сохранён, но привязать чат можно только после настройки бота.
              </p>
            )}
            <p className={styles.muted}>Или отправьте боту команду /start {code.code}</p>
          </>
        )}
        <Actions>
          <button type="button" onClick={() => setCode(null)}>
            Готово
          </button>
        </Actions>
      </Dialog>
    </div>
  );
}
