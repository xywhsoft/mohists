#ifndef MOHISTS_SCHEMAS_H
#define MOHISTS_SCHEMAS_H
static const char MhTeamSchema[] =
    "{\"type\":\"object\",\"properties\":{"
    "\"action\":{\"type\":\"string\",\"enum\":[\"start\",\"get\",\"assign\",\"execute\",\"run\",\"wait\",\"result\",\"refresh\",\"cancel\",\"stop\",\"finish\"]},"
    "\"id\":{\"type\":\"string\"},\"goal\":{\"type\":\"string\"},"
    "\"member\":{\"type\":\"string\"},\"role\":{\"type\":\"string\",\"enum\":[\"researcher\",\"worker\",\"reviewer\"]},"
    "\"title\":{\"type\":\"string\"},\"prompt\":{\"type\":\"string\"},"
    "\"depends_on\":{\"type\":\"array\",\"items\":{\"type\":\"string\"}},"
    "\"expected_revision\":{\"type\":\"integer\",\"minimum\":0},"
    "\"timeout_ms\":{\"type\":\"integer\",\"minimum\":0,\"maximum\":60000}},\"required\":[\"action\"]}";
static const char* MhTeamActions[] = {"start", "get", "assign", "execute", "run", "wait", "result", "refresh", "cancel", "stop", "finish"};
static bool MhTeamToolAction(const char* Action) {
    for (size_t I = 0; I < sizeof(MhTeamActions)/sizeof(*MhTeamActions); ++I)
        if (Action && !strcmp(Action, MhTeamActions[I])) return true;
    return false;
}
#endif
