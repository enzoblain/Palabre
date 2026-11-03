# Mobile app: v1 user stories

User stories and acceptance criteria for the Palabre mobile app. Author: Chloé (Product Owner). For the technical design of the app, see [Mobile app](mobile.md).

Common rules for every story: iPhone first, Android from the same code, look and feel close to iMessage (Emma's spec). The user is the CEO.

## v1 scope and priority

v1 covers S1 to S6 and S8 only, not every screen of the web app. Priorities: P1 first, then P2.

| Story | Title | Priority |
| --- | --- | --- |
| S1 | Sign in | P1 |
| S2 | Conversation list | P1 |
| S3 | Read a conversation | P1 |
| S4 | Write in #direction | P1 |
| S5 | Automatic updates | P2 |
| S6 | Team status | P2 |
| S8 | Long session | P2 |

Each criterion below is written so that QA can test it.

## Stories

### S1 Sign in (P1)

As the CEO, I sign in from my phone with the server URL and the admin token, so I can follow my team away from the office.

- S1.1 With a valid URL and token, I land on the conversation list.
- S1.2 With a wrong token, a clear error message is shown and nothing is stored.
- S1.3 With an unreachable server, the message is distinct from the "wrong token" one.
- S1.4 After closing the app, I stay signed in as long as the session is valid.
- S1.5 When the session has expired, I am sent back to the sign-in screen without losing the URL.

### S2 Conversation list (P1)

As the CEO, I see my conversations sorted by last message, with a preview and a time, like the iMessage list.

- S2.1 Conversations are sorted by most recent message.
- S2.2 An empty list shows an explicit message.
- S2.3 Pull to refresh reloads the list.
- S2.4 On a network error, a banner with a "Retry" button is shown.

### S3 Read a conversation (P1)

As the CEO, I see the messages as bubbles: mine on the right, the team's on the left with the author's name.

- S3.1 Messages are in chronological order and the conversation opens on the last message.
- S3.2 The author is shown for team messages.
- S3.3 The back gesture or button returns to the list.
- S3.4 An empty conversation shows an explicit message.

### S4 Write in #direction (P1)

As the CEO, I send a message to the lead from the app.

- S4.1 After sending, the message appears in less than 2 seconds.
- S4.2 With an empty message, the send button is disabled.
- S4.3 If sending fails, the message stays visible with an error mark and can be sent again.

### S5 Automatic updates (P2)

As the CEO, new messages arrive without any action from me; updates pause in the background.

- S5.1 A message posted elsewhere appears in less than 5 seconds while the app is open.
- S5.2 With the app in the background, no request is made.
- S5.3 Coming back to the foreground refreshes immediately.

### S6 Team status (P2)

As the CEO, I see who is busy or available.

- S6.1 Each member has a busy or available indicator.
- S6.2 The indicators update together with the list.

### S8 Long session (P2)

As the CEO, I do not re-enter the token every 12 hours (point raised by Maya).

- S8.1 No manual re-entry before X days. X is to be decided with Enzo; the change may need a backend decision.

## Out of v1

- Notifications push (formerly S7, P3): needs a separate backend task.
- Reactions.
- Photos.

## Open points (waiting for Enzo)

- iMessage scope: does "99% iMessage" include reactions, photos and dark mode? Proposal: dark mode yes, reactions and photos not in v1.
- Session duration: the value of X in S8.1.
