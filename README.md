n8n / cURL examples (ready)

Start job (POST):

curl -X POST "https://<your-repl>.repl.co/render" \
 -H "Content-Type: application/json" \
 -d '{
  "resolution":"1080x1920",
  "scenes":[
    {"duration":5,"elements":[{"type":"image","src":"https://images.pexels.com/photos/19783674/pexels-photo-19783674.jpeg"}]},
    {"duration":5,"elements":[{"type":"image","src":"https://images.pexels.com/photos/19437845/pexels-photo-19437845.jpeg"}]}
  ],
  "elements":[ {"type":"audio","src":"https://files.catbox.moe/vzbloq.mp3"} ]
}'


Check status:

curl -X GET "https://<your-repl>.repl.co/status/<job_id>"


Download result:

curl -L "https://<your-repl>.repl.co/result/<job_id>.mp4" -o final.mp4


N8N: Use the POST node (CreateJob) → Wait node → HTTP GET node with URL:

https://<your-repl>.repl.co/status/{{$node["CreateJob"].json["job_id"]}}


If status == done → GET result with https://<your-repl>.repl.co{{$json["video_url"]}} (Response Format: File).
