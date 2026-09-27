# Firebase Emulator Suite image (Java is not required on the host).
FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g firebase-tools@15 \
    && firebase setup:emulators:firestore \
    && firebase setup:emulators:database \
    && firebase setup:emulators:storage \
    && firebase setup:emulators:ui

WORKDIR /srv
COPY firebase.json ./firebase.json
COPY firebase ./firebase

EXPOSE 4000 4400 4500 8080 9000 9099 9199

CMD ["firebase", "emulators:start", "--project", "demo-oltivra", "--only", "auth,firestore,database,storage"]
