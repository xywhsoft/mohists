#ifndef MOHISTS_HISTORY_H
#define MOHISTS_HISTORY_H
#include "mdo/instance.h"

static mdo_result MhHistory(MhContext* C, const xvalue* P, xvalue** R, mdo_error_v1* E) {
    const char* Member = MhText(C, P, "member");
    if (!Member && C->S->MemberId && C->S->MemberId[0]) Member = C->S->MemberId;
    if (!MhId(Member, 48)) return MhError(E, "mohists_arguments", "Select a member from this collaboration group", 400);
    xvalue* Q = MhParams(C, C->Group); MhString(C, Q, "id", Member);
    MhNumber(C, Q, "after", MhUInt(C, P, "after"));
    MhNumber(C, Q, "limit", C->V->Get(P, "limit") ? MhUInt(C, P, "limit") : 16);
    mdo_result Code = mdoInstanceHistory(C->S, Q, R, E); C->V->Release(Q); return Code;
}

#endif
