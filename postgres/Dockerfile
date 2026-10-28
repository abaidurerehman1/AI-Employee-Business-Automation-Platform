FROM postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24 AS build
RUN apk add --no-cache build-base curl \
    && curl -fsSL https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.0.tar.gz -o /tmp/pgvector.tar.gz \
    && tar -xzf /tmp/pgvector.tar.gz -C /tmp \
    && make -C /tmp/pgvector-0.8.0 OPTFLAGS="" with_llvm=no \
    && make -C /tmp/pgvector-0.8.0 with_llvm=no install

FROM postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24
COPY --from=build /usr/local/lib/postgresql/vector.so /usr/local/lib/postgresql/vector.so
COPY --from=build /usr/local/share/postgresql/extension/vector* /usr/local/share/postgresql/extension/
