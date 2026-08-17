{{- define "sauron.name" -}}sauron{{- end -}}
{{- define "sauron.image" -}}
{{- printf "%s%s:%s" (ternary (printf "%s/" .Values.image.registry) "" (ne .Values.image.registry "")) .repository .Values.image.tag -}}
{{- end -}}

{{- define "sauron.deepstream.replicas" -}}
{{- if gt (int .Values.deepstream.replicas) 0 -}}
{{ .Values.deepstream.replicas }}
{{- else if eq .Values.profile "m" -}}3
{{- else if eq .Values.profile "s" -}}2
{{- else -}}1
{{- end -}}
{{- end -}}
