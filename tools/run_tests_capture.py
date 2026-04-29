import sys
import subprocess

cmd = [sys.executable, 'manage.py', 'test', '-v', '2']
print('Running:', ' '.join(cmd))
proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
with open('test_output_utf8.log', 'wb') as f:
    f.write(proc.stdout)
print('WROTE', len(proc.stdout), 'bytes to test_output_utf8.log')
sys.exit(proc.returncode)
