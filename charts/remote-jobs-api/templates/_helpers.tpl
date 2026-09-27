{{- define "remote-jobs-api.name" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "remote-jobs-api.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "remote-jobs-api.labels" -}}
helm.sh/chart: {{ include "remote-jobs-api.chart" . }}
{{ include "remote-jobs-api.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "remote-jobs-api.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "remote-jobs-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "remote-jobs-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "remote-jobs-api.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "remote-jobs-api.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "remote-jobs-api.adminSecretName" -}}
{{- if .Values.adminToken.existingSecret -}}
{{- .Values.adminToken.existingSecret -}}
{{- else -}}
{{- if .Values.adminToken.name -}}
{{- .Values.adminToken.name -}}
{{- else -}}
{{- printf "rja-%s" .Release.Name -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "remote-jobs-api.image" -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag -}}
{{- end -}}
