# ============================================
# 阶段一：Maven 编译打包
# ============================================
# Use an accessible registry by default; override these build args when
# deploying in an environment with direct Docker Hub access.
ARG MAVEN_BASE_IMAGE=dockerproxy.net/library/maven:3.9-eclipse-temurin-17-alpine
ARG JAVA_BASE_IMAGE=dockerproxy.net/library/eclipse-temurin:17-jre-alpine

FROM ${MAVEN_BASE_IMAGE} AS builder

WORKDIR /build
COPY pom.xml .
COPY .mvn/settings.xml .mvn/settings.xml
# 先下载依赖（利用 Docker 缓存层）
RUN mvn -s .mvn/settings.xml dependency:go-offline -B -q || true
COPY src/ ./src/
RUN mvn -s .mvn/settings.xml package -DskipTests -B -q

# ============================================
# 阶段二：JRE 运行镜像
# ============================================
FROM ${JAVA_BASE_IMAGE} AS runtime

# 创建非 root 用户
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

WORKDIR /app

# 复制 JAR
COPY --from=builder /build/target/*.jar app.jar

# 创建上传目录
RUN mkdir -p /app/upload && chown -R appuser:appgroup /app

# 切换到非 root 用户
USER appuser

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD wget -q --spider http://localhost:18080/api/site/info || exit 1

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "app.jar"]
