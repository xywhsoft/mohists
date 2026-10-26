#ifndef MOHISTS_MESSAGES_H
#define MOHISTS_MESSAGES_H

/* A dedicated collaboration mailbox never masquerades as direct user input.
 * Sending is passive. Only explicit coordinator scheduling runs a model. */
static mdo_result MhMessages(MhContext* C, const xvalue* P, const char* Action,
    xvalue** R, mdo_error_v1* E) {
    const char* Recipient = MhText(C, P, "to");
    if (!Recipient) Recipient = C->S->MemberId && C->S->MemberId[0] ? C->S->MemberId : "coordinator";
    if (!MhId(Recipient, 48)) return MhError(E, "mohists_arguments", "Supply a portable recipient", 400);
    if (strcmp(Action, "message") && C->S->MemberId && C->S->MemberId[0] && strcmp(C->S->MemberId, Recipient))
        return MhError(E, "mohists_mailbox_owner", "Members can consume only their own mailbox", 403);
    if (strcmp(Recipient, "coordinator")) {
        xvalue* Q = MhParams(C, C->Group), *Member = NULL; MhString(C, Q, "id", Recipient);
        mdo_result Code = MhCall(C, "instance.get", Q, &Member, E); C->V->Release(Member); if (Code) return Code;
    }
    char Box[96]; snprintf(Box, sizeof(Box), "mohists.%s", Recipient);
    xvalue* Q = MhParams(C, C->Group); MhString(C, Q, "mailbox", Box);
    if (!strcmp(Action, "message")) {
        const char* Id = MhText(C, P, "message_id"), *Text = MhText(C, P, "text");
        if (!MhId(Id, 64) || !Text || !Text[0] || strlen(Text) > 4096) {
            C->V->Release(Q); return MhError(E, "mohists_arguments", "Supply message_id and text of 1..4096 bytes", 400);
        }
        xvalue* Body = C->V->Object(); MhString(C, Body, "text", Text);
        MhString(C, Body, "source", mdoCallOrigin(C->S) == MDO_ORIGIN_USER ? "user" : "agent");
        MhString(C, Body, "from", C->S->MemberId && C->S->MemberId[0] ? C->S->MemberId : "coordinator");
        MhSet(C, Q, "body", Body); MhString(C, Q, "message_id", Id);
    } else if (!strcmp(Action, "ack")) {
        MhString(C, Q, "message_id", MhText(C, P, "message_id"));
    } else {
        MhNumber(C, Q, "after", MhUInt(C, P, "after")); MhNumber(C, Q, "limit", 16);
    }
    const char* Method = !strcmp(Action, "message") ? "mailbox.send" : !strcmp(Action, "ack") ? "mailbox.ack" : "mailbox.read";
    mdo_result Code = MhCall(C, Method, Q, R, E); if (!Code && !strcmp(Action, "message")) MhEmit(C, "mohists.message", *R);
    return Code;
}

#endif
