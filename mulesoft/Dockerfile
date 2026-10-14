# Builds the Mule app and runs it on the free Mule runtime (Community Edition).
#   docker build -t order-system-api mulesoft/
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /src
COPY order-system-api/ .
RUN mvn -q -B package

FROM eclipse-temurin:17-jre
ARG MULE_VERSION=4.12.0
ADD https://repository.mulesoft.org/releases/org/mule/distributions/mule-standalone/${MULE_VERSION}/mule-standalone-${MULE_VERSION}.tar.gz /tmp/mule.tar.gz
RUN tar xzf /tmp/mule.tar.gz -C /opt && mv /opt/mule-standalone-${MULE_VERSION} /opt/mule && rm /tmp/mule.tar.gz
COPY --from=build /src/target/*-mule-application.jar /opt/mule/apps/
EXPOSE 8081
# ERP location is overridable: -M-Derp.host=... -M-Derp.port=...
CMD ["/opt/mule/bin/mule", "-M-Derp.host=mock-erp", "-M-Derp.port=8001"]
