{{/*
Expand the name of the chart.
*/}}
{{- define "ico-cache.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "ico-cache.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "ico-cache.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "ico-cache.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "ico-cache.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ico-cache.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Tenant API Keys JSON string
*/}}
{{- define "ico-cache.apiKeysJson" -}}
{
{{- $first := true -}}
{{- range .Values.tenants.list }}
  {{- if not $first }},{{ end }}
  {{- $first = false }}
  "{{ .api_key }}": "{{ .id }}"
{{- end }}
}
{{- end }}

{{/*
Resolve a container image reference, preferring an immutable digest when set.
Usage: {{ include "ico-cache.image" .Values.api.image }}
*/}}
{{- define "ico-cache.image" -}}
{{- if .digest -}}
{{- printf "%s@%s" .repository .digest -}}
{{- else -}}
{{- printf "%s:%s" .repository (.tag | default "latest") -}}
{{- end -}}
{{- end }}

{{/*
Name of the Secret consumed by the API and worker pods.
*/}}
{{- define "ico-cache.secretName" -}}
{{- if .Values.externalSecrets.enabled -}}
{{- .Values.externalSecrets.targetSecretName | default (printf "%s-secrets" (include "ico-cache.fullname" .)) -}}
{{- else -}}
{{- .Values.secrets.existingSecret | default (printf "%s-secrets" (include "ico-cache.fullname" .)) -}}
{{- end -}}
{{- end }}

{{/*
ServiceAccount name to use for pods.
*/}}
{{- define "ico-cache.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "ico-cache.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end }}

{{/*
Common pod-level spec fragments (imagePullSecrets, securityContext, service account).
Rendered with $ (root context) and the component's podSecurityContext.
Usage: {{ include "ico-cache.podSpec" (dict "ctx" $ "podSecurityContext" .Values.api.podSecurityContext) }}
*/}}
{{- define "ico-cache.podSpec" -}}
{{- $ctx := .ctx -}}
serviceAccountName: {{ include "ico-cache.serviceAccountName" $ctx }}
{{- with $ctx.Values.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
securityContext:
  {{- toYaml .podSecurityContext | nindent 2 }}
{{- end }}

