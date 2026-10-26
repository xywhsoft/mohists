#ifndef MOHISTS_HISTORY_H
#define MOHISTS_HISTORY_H
#include "mdo/instance.h"

static mdo_result MhHistory(MhContext* C, const xvalue* P, xvalue** R, mdo_error_v1* E) {
    const char* Member = MhText(C, P, "member");
    if (!Member && C->S->MemberId && C->S->MemberId[0]) Member = C->S->MemberId;
    if (!MhId(Member, 48)) return MhError(E, "mohists_arguments", "Select a member from this collaboration group", 400);
    uint64_t Generation = C->V->Get(P, "generation") ? MhUInt(C, P, "generation") : C->Generation;
    if (!Generation || Generation > C->Generation || (C->S->MemberId && C->S->MemberId[0] && Generation != C->Generation))
        return MhError(E, "mohists_history_group", "Select a recorded collaboration generation in this conversation", 400);
    char Group[128]; snprintf(Group, sizeof(Group), "%s.g%llu", C->Root, (unsigned long long)Generation);
    xvalue* Q = MhParams(C, Group); MhString(C, Q, "id", Member);
    MhNumber(C, Q, "after", MhUInt(C, P, "after"));
    MhNumber(C, Q, "limit", C->V->Get(P, "limit") ? MhUInt(C, P, "limit") : 16);
    mdo_result Code = mdoInstanceHistory(C->S, Q, R, E); C->V->Release(Q); return Code;
}

#endif
