# Build environment for the WhatIsUp mobile (Capacitor / Android) app.
#
# Provides Node 20, JDK 17 and the Android cmdline-tools + platform-tools needed
# to run `npx cap add android`, `npx cap sync` and `./gradlew assembleDebug`.
#
# Build:   docker build -t whatisup-mobile mobile/
# Use:     see mobile/build.sh

FROM eclipse-temurin:21-jdk-jammy

ENV DEBIAN_FRONTEND=noninteractive \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_HOME=/opt/android-sdk \
    PATH=/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:/opt/android-sdk/build-tools/34.0.0:$PATH

ARG ANDROID_API=34
ARG BUILD_TOOLS=34.0.0
ARG CMDLINE_TOOLS_VERSION=11076708

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl unzip git ca-certificates \
        # Node 20 from NodeSource
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p ${ANDROID_SDK_ROOT}/cmdline-tools \
    && cd /tmp \
    && curl -fsSLo tools.zip "https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS_VERSION}_latest.zip" \
    && unzip -q tools.zip -d ${ANDROID_SDK_ROOT}/cmdline-tools \
    && mv ${ANDROID_SDK_ROOT}/cmdline-tools/cmdline-tools ${ANDROID_SDK_ROOT}/cmdline-tools/latest \
    && rm tools.zip

RUN yes | sdkmanager --licenses >/dev/null \
    && sdkmanager \
        "platform-tools" \
        "platforms;android-${ANDROID_API}" \
        "build-tools;${BUILD_TOOLS}" >/dev/null

WORKDIR /workspace
