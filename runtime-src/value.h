#ifndef MOHISTS_VALUE_H
#define MOHISTS_VALUE_H

typedef struct MhContext {
    const mdo_sdk_context_v1* S;
    const mdo_values_v1* V;
    char Root[128], Group[128];
} MhContext;

static const char* MhText(const MhContext* C, const xvalue* P, const char* K) {
    return C->V->Text(C->V->Get(P, K));
}
static uint64_t MhUInt(const MhContext* C, const xvalue* P, const char* K) {
    uint64_t N = 0; int64_t I = 0; const xvalue* V = C->V->Get(P, K);
    if (!C->V->Unsigned(V, &N) && C->V->Integer(V, &I) && I >= 0) N = (uint64_t)I;
    return N;
}
static bool MhIs(const MhContext* C, const xvalue* P, const char* K, const char* S) {
    const char* T = MhText(C, P, K); return T && !strcmp(T, S);
}
static bool MhSet(const MhContext* C, xvalue* P, const char* K, xvalue* V) {
    bool Ok = V && C->V->Set(P, K, V); C->V->Release(V); return Ok;
}
static bool MhString(const MhContext* C, xvalue* P, const char* K, const char* S) {
    return MhSet(C, P, K, C->V->String(S ? S : ""));
}
static bool MhNumber(const MhContext* C, xvalue* P, const char* K, uint64_t N) {
    return MhSet(C, P, K, C->V->UInt(N));
}
static mdo_result MhError(mdo_error_v1* E, const char* Code, const char* Message, unsigned Status) {
    if (E) { E->Size = sizeof(*E); E->Status = Status;
        snprintf(E->Code, sizeof(E->Code), "%s", Code);
        snprintf(E->Message, sizeof(E->Message), "%s", Message);
        snprintf(E->Stage, sizeof(E->Stage), "mohists"); }
    return MDO_RESULT_ERROR;
}
static bool MhId(const char* S, size_t Max) {
    if (!S || !S[0] || strlen(S) > Max || S[0] == '.' || strstr(S, "..")) return false;
    size_t N = strlen(S); if (S[N-1] == '.') return false;
    for (size_t I = 0; I < N; ++I) if (!((S[I] >= 'a' && S[I] <= 'z') ||
        (S[I] >= 'A' && S[I] <= 'Z') || (S[I] >= '0' && S[I] <= '9') ||
        S[I] == '.' || S[I] == '_' || S[I] == '-')) return false;
    return true;
}
static mdo_result MhContextInit(MhContext* C, const mdo_sdk_context_v1* S, mdo_error_v1* E) {
    memset(C, 0, sizeof(*C)); C->S = S; C->V = S->Api->Values;
    if (!MhId(S->SessionId, 80)) return MhError(E, "mohists_session", "Select an owning conversation", 400);
    snprintf(C->Root, sizeof(C->Root), "mohists.%s", S->SessionId);
    return MDO_RESULT_OK;
}
static xvalue* MhParams(const MhContext* C, const char* Namespace) {
    xvalue* P = C->V->Object(); MhString(C, P, "namespace", Namespace); return P;
}
static mdo_result MhCall(const MhContext* C, const char* M, xvalue* P, xvalue** R, mdo_error_v1* E) {
    mdo_result Code = mdoCall(C->S, M, P, R, E); C->V->Release(P); return Code;
}
static mdo_result MhLoad(const MhContext* C, const char* Key, xvalue** R, mdo_error_v1* E) {
    xvalue* P = MhParams(C, C->Root); MhString(C, P, "key", Key);
    return MhCall(C, "state.get", P, R, E);
}
static mdo_result MhSave(const MhContext* C, const char* Key, uint64_t Rev,
    const xvalue* Value, xvalue** R, mdo_error_v1* E) {
    xvalue* P = MhParams(C, C->Root); MhString(C, P, "key", Key);
    MhNumber(C, P, "expected_revision", Rev); C->V->Set(P, "value", Value);
    return MhCall(C, "state.compare_exchange", P, R, E);
}
static mdo_result MhTeamLoad(MhContext* C, xvalue** Envelope, xvalue** Team, mdo_error_v1* E) {
    mdo_result Code = MhLoad(C, "team", Envelope, E); if (Code) return Code;
    const xvalue* V = C->V->Get(*Envelope, "value");
    if (!V) return MhError(E, "mohists_team_missing", "Start a collaboration group first", 404);
    *Team = C->V->Clone(V);
    snprintf(C->Group, sizeof(C->Group), "%s.g%llu", C->Root, (unsigned long long)MhUInt(C, V, "generation"));
    if (C->S->Namespace && C->S->Namespace[0] && strcmp(C->S->Namespace, C->Group))
        return MhError(E, "mohists_stale_group", "This member belongs to a previous collaboration group", 409);
    return MDO_RESULT_OK;
}
static mdo_result MhCoordinator(const MhContext* C, mdo_error_v1* E) {
    return C->S->MemberId && C->S->MemberId[0] ?
        MhError(E, "mohists_coordinator_only", "Only the coordinator or user can change the team", 403) : MDO_RESULT_OK;
}
static void MhEmit(const MhContext* C, const char* Topic, const xvalue* Value) {
    xvalue* P = C->V->Object(), *R = NULL; mdo_error_v1 E = {0};
    MhString(C, P, "topic", Topic); if (Value) C->V->Set(P, "data", Value);
    MhCall(C, "events.emit", P, &R, &E); C->V->Release(R);
}
static xvalue* MhTransactionWrite(const MhContext* C, const char* Key,
    uint64_t Revision, const xvalue* Value) {
    xvalue* W = C->V->Object(); MhString(C, W, "key", Key);
    MhNumber(C, W, "expected_revision", Revision); C->V->Set(W, "value", Value); return W;
}
static mdo_result MhSavePair(const MhContext* C, const xvalue* TeamEnvelope,
    const xvalue* Team, const char* Key, const xvalue* Envelope, const xvalue* Value,
    xvalue** R, mdo_error_v1* E) {
    xvalue* P = MhParams(C, C->Root), *Writes = C->V->Array();
    xvalue* W = MhTransactionWrite(C, "team", MhUInt(C, TeamEnvelope, "revision"), Team);
    C->V->Append(Writes, W); C->V->Release(W);
    W = MhTransactionWrite(C, Key, MhUInt(C, Envelope, "revision"), Value);
    C->V->Append(Writes, W); C->V->Release(W); MhSet(C, P, "writes", Writes);
    return MhCall(C, "state.transaction", P, R, E);
}

#endif
