import { Button, Stack, Typography } from '@mui/material';
import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <Stack alignItems="center" spacing={2} sx={{ mt: 10 }}>
      <Typography variant="h4">Page not found</Typography>
      <Button component={Link} to="/" variant="contained">
        Go to overview
      </Button>
    </Stack>
  );
}
