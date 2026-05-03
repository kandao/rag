{{- define "rag.labels" -}}
app.kubernetes.io/name: rag
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "rag.serviceLabels" -}}
{{ include "rag.labels" .root }}
app.kubernetes.io/component: {{ .component }}
app: {{ .app }}
{{- end -}}

{{- define "rag.envFrom" -}}
{{- $svc := . -}}
{{- if or $svc.configMapName $svc.secretName }}
envFrom:
{{- if $svc.configMapName }}
  - configMapRef:
      name: {{ $svc.configMapName }}
{{- end }}
{{- if $svc.secretName }}
  - secretRef:
      name: {{ $svc.secretName }}
      optional: {{ default false $svc.secretOptional }}
{{- end }}
{{- end }}
{{- end -}}
